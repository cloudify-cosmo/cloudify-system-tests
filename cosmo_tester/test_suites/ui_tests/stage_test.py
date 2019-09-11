########
# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

# import pytest

from cosmo_tester.framework.fixtures import image_based_manager
from cosmo_tester.framework import util

import subprocess
import os

manager = image_based_manager


def test_ui(cfy, manager, module_tmpdir, attributes, ssh_key, logger):

    if os.environ["UPDATE_STAGE_ON_MANAGER"] == 'true':
        logger.info('Starting update of Stage package on Manager...')
        if os.environ["CENTOS_MANAGER"] == 'false':
            logger.info('Setting Manager user to cloud-user')
            os.environ["MANAGER_USER"] = 'cloud-user'
        os.environ["MANAGER_IP"] = manager.ip_address
        os.environ["SSH_KEY_PATH"] = ssh_key.private_key_path
        if not os.environ["STAGE_PACKAGE_URL"]:
            logger.info('Creating Stage package...')
            subprocess.call(['npm', 'run', 'beforebuild'],
                            cwd=os.environ["CLOUDIFY_STAGE_REPO_PATH"])
            subprocess.call(['npm', 'run', 'build'],
                            cwd=os.environ["CLOUDIFY_STAGE_REPO_PATH"])
            subprocess.call(['npm', 'run', 'zip'],
                            cwd=os.environ["CLOUDIFY_STAGE_REPO_PATH"])
        logger.info('Uploading Stage package...')
        subprocess.call(['npm', 'run', 'upload'],
                        cwd=os.environ["CLOUDIFY_STAGE_REPO_PATH"])

    license_path = util.get_resource_path('test_valid_paying_license.yaml')
    manager.client.license.upload(license_path)

    logger.info('Starting Stage system tests...')
    os.environ["STAGE_E2E_SELENIUM_HOST"] = '10.239.0.203'
    os.environ["STAGE_E2E_MANAGER_URL"] = manager.ip_address
    subprocess.call(['npm', 'run', 'e2e'],
                    cwd=os.environ["CLOUDIFY_STAGE_REPO_PATH"])
