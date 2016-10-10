########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

from cosmo_tester.framework.testenv import TestCase
from selenium.common.exceptions import NoSuchElementException

import logging
import cloudify.utils

for logger_name in ('sh', 'pika', 'requests.packages.urllib3.connectionpool'):
    cloudify.utils.setup_logger(logger_name, logging.WARNING)

PHANTOMJS_FILE_NAME = 'phantomjs-2.1.1-linux-x86_64'


class TelecomBase(TestCase):
    def _verify_telecom_manager_edition(self):
        self.logger.info('Verifying manager edition...')

        try:
            self.driver.get('http://' + self.get_manager_ip())
        except Exception:
            self.logger.info('Failed to get manager ip.')

        edition = 'Standard Edition'
        try:
            edition = self.driver.find_element_by_class_name(
                'ui-variation-brand').text
        except NoSuchElementException:
            self.logger.info('Telecom Edition UI element not found.')

        self.assertEqual(edition, 'Telecom Edition',
                         'The manager is not Telecom Edition')
        self.logger.info('Test passed. The manager is Telecom Edition.')
        self.driver.close()
