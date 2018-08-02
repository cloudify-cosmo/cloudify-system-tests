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


import logging
import os
import sys

from path import Path
import pytest
import sh

from cosmo_tester.framework import util


@pytest.fixture(scope='module')
def logger(request):
    logger = logging.getLogger(request.module.__name__)
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter(fmt='%(asctime)s [%(levelname)s] '
                                      '[%(name)s] %(message)s',
                                  datefmt='%H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.propagate = False
    return logger


@pytest.fixture(scope='module')
def module_tmpdir(request, tmpdir_factory, logger):
    suffix = request.module.__name__
    temp_dir = Path(tmpdir_factory.mktemp(suffix))
    logger.info('Created temp folder: %s', temp_dir)

    return temp_dir


@pytest.fixture(scope='module')
def ssh_key(module_tmpdir, logger):
    key = SSHKey(module_tmpdir, logger)
    key.create()
    return key


@pytest.fixture(scope='module')
def attributes(logger):
    return util.get_attributes(logger)


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
