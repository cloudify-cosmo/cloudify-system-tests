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

from nose.tools import nottest
from test_cli_package import TestCliPackage
from ubuntu_base import Ubuntu14Base
from telecom_base import TelecomBase
from cosmo_tester.framework.ui_phantomjs_env import UiPhantomjsEnv


class TestUbuntu14(Ubuntu14Base, TestCliPackage):

    def test_ubuntu14_cli_package(self):
        self._add_dns()
        self._test_cli_package()


class TestUbuntu14Telecom(Ubuntu14Base, TestCliPackage, TelecomBase):
    @property
    def package_parameter_name(self):
        return 'DEBIAN_TELCO_CLI_PACKAGE_URL'

    @nottest
    def test_ubuntu14_telecom_cli_package(self):
        self._add_dns()
        self._test_cli_package()
        self.driver = UiPhantomjsEnv.setup_phantomjs_env()
        self._verify_telecom_manager_edition()
