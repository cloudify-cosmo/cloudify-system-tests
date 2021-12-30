import pytest
from path import Path

from cosmo_tester.framework.config import load_config
from cosmo_tester.framework.logger import get_logger
from cosmo_tester.framework.test_hosts import Hosts, VM
from cosmo_tester.framework.util import SSHKey
from cosmo_tester.test_suites.cluster.conftest import (
    _get_hosts, restore_from_xfs, reboot_if_required)


@pytest.fixture(scope='module')
def logger(request):
    return get_logger(request.module.__name__)


@pytest.fixture(scope='module')
def module_tmpdir(request, tmpdir_factory, logger):
    suffix = request.module.__name__
    temp_dir = Path(tmpdir_factory.mktemp(suffix))
    logger.info('Created temp folder: %s', temp_dir)

    return temp_dir


@pytest.fixture(scope='session')
def session_tmpdir(request, tmpdir_factory, session_logger):
    suffix = 'session'
    temp_dir = Path(tmpdir_factory.mktemp(suffix))
    session_logger.info('Created temp folder: %s', temp_dir)

    return temp_dir


@pytest.fixture(scope='session')
def ssh_key(session_tmpdir, session_logger):
    key = SSHKey(session_tmpdir, session_logger)
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


@pytest.fixture(scope='session')
def test_config(request):
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


@pytest.fixture(scope='session')
def session_logger(request):
    return get_logger('session')


@pytest.fixture(scope='session')
def session_manager(request, ssh_key, session_tmpdir, test_config,
                    session_logger):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True)
    hosts.create()
    hosts.dump_xfs()
    yield hosts.instances[0]
    hosts.destroy()


@pytest.fixture(scope='function')
def image_based_manager(session_manager):
    reboot_if_required(session_manager)
    session_manager.bootstrap()
    yield session_manager
    session_manager.teardown()
    restore_from_xfs(session_manager, logger)


@pytest.fixture(scope='function')
def function_scoped_manager(request, ssh_key, session_tmpdir, test_config,
                            session_logger):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True)
    hosts.create()
    yield hosts.instances[0]
    hosts.destroy()


@pytest.fixture(scope='session')
def three_plus_one_session_vms(ssh_key, session_tmpdir, test_config,
                               session_logger, request):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True,
                  number_of_instances=4)
    hosts.instances[-1] = VM('centos_7', test_config)

    hosts.create()
    hosts.dump_xfs()
    yield hosts.instances
    hosts.destroy()


@pytest.fixture(scope='function')
def three_node_cluster_with_extra_node(test_config, session_logger,
                                       three_plus_one_session_vms):
    reboot_if_required(three_plus_one_session_vms)
    yield _get_hosts(three_plus_one_session_vms,
                     test_config, session_logger,
                     pre_cluster_rabbit=True,
                     three_nodes_cluster=True,
                     extra_node=True)
    restore_from_xfs(three_plus_one_session_vms, logger)


@pytest.fixture(scope='session')
def three_plus_manager_session_vms(ssh_key, session_tmpdir, test_config,
                                   session_logger, request):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True,
                  number_of_instances=4)

    hosts.create()
    hosts.dump_xfs()
    yield hosts.instances
    hosts.destroy()


@pytest.mark.parametrize('three_plus_one_session_vms', ['master'],
                         indirect=['three_plus_one_session_vms'])
@pytest.fixture(scope='function')
def three_node_cluster_with_extra_manager(test_config, session_logger,
                                          three_plus_manager_session_vms):
    reboot_if_required(three_plus_manager_session_vms)
    yield _get_hosts(three_plus_manager_session_vms,
                     test_config, session_logger,
                     pre_cluster_rabbit=True,
                     three_nodes_cluster=True,
                     extra_node=True)
    restore_from_xfs(three_plus_manager_session_vms, logger)

