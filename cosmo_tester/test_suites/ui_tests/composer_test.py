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

import subprocess
import os


def test_ui(cfy, image_based_manager, module_tmpdir, ssh_key, logger):

    logger.info('Installing dependencies to run system tests...')
    subprocess.call(['npm', 'ci'],
                    cwd=os.environ["CLOUDIFY_COMPOSER_REPO_PATH"])
    if os.environ["UPDATE_COMPOSER_ON_MANAGER"] == 'true':
        logger.info('Starting update of Composer package on Manager...')
        os.environ["MANAGER_IP"] = image_based_manager.ip_address
        os.environ["SSH_KEY_PATH"] = ssh_key.private_key_path
        logger.info('Creating Composer package...')
        subprocess.call(['bower', 'install'],
                        cwd=os.environ["CLOUDIFY_COMPOSER_REPO_PATH"])
        subprocess.call(['grunt', 'pack'],
                        cwd=os.environ["CLOUDIFY_COMPOSER_REPO_PATH"])
        logger.info('Uploading Composer package...')
        subprocess.call(['npm', 'run', 'upload'],
                        cwd=os.environ["CLOUDIFY_COMPOSER_REPO_PATH"])

    logger.info('Starting Composer system tests...')
    os.environ["COMPOSER_E2E_MANAGER_URL"] = image_based_manager.ip_address
    subprocess.call(['npm', 'run', 'e2e'],
                    cwd=os.environ["CLOUDIFY_COMPOSER_REPO_PATH"])
