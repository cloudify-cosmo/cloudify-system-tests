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
from test_offline_cli_package import TestOfflineCliPackage
from centos_base import Centos7Base
from telecom_base import TelecomBase
from cosmo_tester.framework.ui_phantomjs_env import UiPhantomjsEnv


class Centos7Bootstrap(Centos7Base, TestCliPackage):
    def test_centos7_cli_package(self):
        self._add_dns()
        self._test_cli_package()


class Centos7OfflineBootstrap(Centos7Base, TestOfflineCliPackage):
    @nottest
    def test_offline_centos7_cli_package(self):
        self._test_cli_package()


class Centos7TelecomBootstrap(Centos7Base, TestCliPackage, TelecomBase):
    @property
    def package_parameter_name(self):
        return 'RHEL_CENTOS_TELCO_CLI_PACKAGE_URL'

    @nottest
    def test_centos7_telecom_cli_package(self):
        self._add_dns()
        self._test_cli_package()
        self.driver = UiPhantomjsEnv.setup_phantomjs_env()
        self._verify_telecom_manager_edition()
