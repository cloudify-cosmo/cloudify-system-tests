import os

import pytest
from path import Path

from cosmo_tester.framework.config import load_config
from cosmo_tester.framework.logger import get_logger
from cosmo_tester.framework.test_hosts import Hosts
from cosmo_tester.test_suites.cluster.conftest import _get_hosts


@pytest.fixture(scope='module')
def logger(request):
    return get_logger(request.module.__name__)


@pytest.fixture(scope='module')
def module_tmpdir(request, tmpdir_factory, logger):
    suffix = request.module.__name__
    temp_dir = Path(tmpdir_factory.mktemp(suffix))
    logger.info('Created temp folder: %s', temp_dir)

    return temp_dir


class SSHKey(object):

    def __init__(self, tmpdir, logger):
        self.private_key_path = tmpdir / 'ssh_key.pem'
        self.public_key_path = tmpdir / 'ssh_key.pem.pub'
        self.logger = logger
        self.tmpdir = tmpdir

    def create(self):
        self.logger.info('Creating SSH keys at: %s', self.tmpdir)
        if os.system("ssh-keygen -t rsa -f {} -q -N ''".format(
                self.private_key_path)) != 0:
            raise IOError('Error creating SSH key: {}'.format(
                    self.private_key_path))
        if os.system('chmod 400 {}'.format(self.private_key_path)) != 0:
            raise IOError('Error setting private key file permission')

    def delete(self):
        self.private_key_path.remove()
        self.public_key_path.remove()


@pytest.fixture(scope='module')
def ssh_key(module_tmpdir, logger):
    key = SSHKey(module_tmpdir, logger)
    key.create()
    return key


def pytest_addoption(parser):
    """Tell the framework where to find the test file."""
    parser.addoption(
        '--config-location',
        action='store',
        default='test_config.yaml',
        help='Location of the test config.',
    )


@pytest.fixture(scope='module')
def test_config(request, logger):
    """Retrieve the test config."""
    # Not using a fixture so that we can use config for logger fixture
    logger = get_logger('config')

    config_file_location = request.config.getoption('--config-location')

    return load_config(logger, config_file_location)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()
    if rep.when == 'call':
        if rep.passed:
            if hasattr(item.session, 'testspassed'):
                item.session.testspassed += 1
            else:
                item.session.testspassed = 1
        elif rep.skipped:
            if hasattr(item.session, 'testsskipped'):
                item.session.testsskipped += 1
            else:
                item.session.testsskipped = 1
        # No need to handle failed, there's a builtin hook for that


@pytest.fixture(scope='module')
def image_based_manager(
        request, ssh_key, module_tmpdir, test_config, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    hosts = Hosts(
        ssh_key, module_tmpdir, test_config, logger, request)
    try:
        hosts.create()
        yield hosts.instances[0]
    finally:
        hosts.destroy()


@pytest.fixture
def three_node_cluster_with_extra_node(ssh_key, module_tmpdir, test_config,
                                       logger, request):
    for _vms in _get_hosts(ssh_key, module_tmpdir, test_config, logger,
                           request, pre_cluster_rabbit=True,
                           three_nodes_cluster=True, extra_node=request.param):
        yield _vms
