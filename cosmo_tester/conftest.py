#########
# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#  * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  * See the License for the specific language governing permissions and
#  * limitations under the License.


import os

import sh
import pytest
from path import Path

from cosmo_tester.framework.config import load_config
from cosmo_tester.framework.logger import get_logger
from cosmo_tester.framework import util
from cosmo_tester.framework.fixtures import *  # noqa


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


@pytest.fixture(scope='module')
def cfy(module_tmpdir, logger):
    os.environ['CFY_WORKDIR'] = module_tmpdir
    logger.info('CFY_WORKDIR is set to %s', module_tmpdir)
    # Copy CLI configuration file if exists in home folder
    # this way its easier to customize the configuration when running
    # tests locally.
    cli_config_path = Path(os.path.expanduser('~/.cloudify/config.yaml'))
    if cli_config_path.exists():
        logger.info('Using CLI configuration file from: %s', cli_config_path)
        new_cli_config_dir = module_tmpdir / '.cloudify'
        new_cli_config_dir.mkdir()
        cli_config_path.copy(new_cli_config_dir / 'config.yaml')
    cfy = util.sh_bake(sh.cfy)
    cfy(['--version'])
    return cfy


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
