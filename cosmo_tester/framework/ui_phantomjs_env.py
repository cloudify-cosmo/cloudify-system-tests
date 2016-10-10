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

import os
from selenium import webdriver
import urllib
import tarfile

PHANTOMJS_FILE_NAME = 'phantomjs-2.1.1-linux-x86_64'


class UiPhantomjsEnv:
    @classmethod
    def setup_phantomjs_env(cls):
        exec_path = os.path.abspath(os.path.join(
            os.path.dirname(__package__),
            PHANTOMJS_FILE_NAME + '/bin/phantomjs'))

        if not os.path.isfile(exec_path):
            urllib.urlretrieve(
                'https://bitbucket.org/ariya/phantomjs/downloads/'
                + PHANTOMJS_FILE_NAME
                + '.tar.bz2',
                PHANTOMJS_FILE_NAME + '.tar.bz2')

            tar = tarfile.open(PHANTOMJS_FILE_NAME + '.tar.bz2', 'r:bz2')
            tar.extractall()
            tar.close()

        return webdriver.PhantomJS(executable_path=exec_path)
