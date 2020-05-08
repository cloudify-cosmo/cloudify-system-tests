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

from cosmo_tester.framework.examples import get_example_deployment


def test_manager_bootstrap_and_deployment(bootstrap_test_manager,
                                          ssh_key, logger, test_config):
    bootstrap_test_manager.bootstrap()
    bootstrap_test_manager.use()

    example = get_example_deployment(bootstrap_test_manager,
                                     ssh_key, logger, 'bootstrap',
                                     test_config)
    example.upload_and_verify_install()
    example.uninstall()
