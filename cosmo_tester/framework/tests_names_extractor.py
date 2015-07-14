#########
# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
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

import json
import os

from nose.plugins import collect


def _extract_test_info(test):
    return '{0}:{1}.{2}'.format(test.test.__module__,
                                type(test.test).__name__,
                                test.test._testMethodName)


def _write_tests_list(tests_list, test_list_path):
    with open(test_list_path, 'w') as outfile:
        print 'write to: {0}'.format(os.path.abspath(test_list_path))
        json.dump(tests_list, outfile, indent=4)


class TestsNamesExtractor(collect.CollectOnly):

    name = 'testnameextractor'
    enableOpt = 'test_name_extractor'

    def __init__(self):
        super(TestsNamesExtractor, self).__init__()
        self.accumulated_tests = []
        self.tests_list_path = None

    def options(self, parser, env):
        super(collect.CollectOnly, self).options(parser, env)
        parser.add_option('--tests-list-path', default='nose.cfy')

    def configure(self, options, conf):
        super(TestsNamesExtractor, self).configure(options, conf)
        self.tests_list_path = options.tests_list_path

    def addSuccess(self, test):
        self.accumulated_tests.append(_extract_test_info(test))

    def finalize(self, result):
        print 'acc tests: {0}'.format(self.accumulated_tests)
        _write_tests_list(self.accumulated_tests, self.tests_list_path)
