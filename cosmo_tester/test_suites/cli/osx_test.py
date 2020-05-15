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


import os

import shutil

from path import Path
import pytest
import yaml
import jinja2

from cosmo_tester.framework.util import (
    get_resource_path,
    is_community,
)


@pytest.fixture(scope='function')
def package_tester(request, ssh_key, attributes, tmpdir, logger):
    _package_tester_mapping = {
        'osx': _OSXCliPackageTester,
    }
    platform = request.param
    tester_class = _package_tester_mapping[platform]

    logger.info('Using temp dir: %s', tmpdir)
    tmpdir = Path(tmpdir)

    tester = tester_class(tmpdir, attributes, ssh_key, logger)

    yield tester

    tester.perform_cleanup()


# Currently skipped while deciding approach under new blueprint based
# deployments
@pytest.mark.parametrize('package_tester', ['osx'], indirect=True)
def _test_cli_on_osx(package_tester, attributes):
    inputs = {
        'manager_image': attributes.centos_7_AMI,
        'manager_flavor': attributes.large_AWS_type,
        'manager_user': attributes.centos_7_username,
        'osx_public_ip': os.environ["MACINCLOUD_HOST"],
        'osx_user': os.environ["MACINCLOUD_USERNAME"],
        'osx_password': os.environ["MACINCLOUD_PASSWORD"],
        'osx_ssh_key': os.environ["MACINCLOUD_SSH_KEY"],
        'cli_cloudify': os.environ["CLI_CLOUDIFY"],
        'cloudify_rpm_url': None,  # Will need repopulating when fixing this
        'cloudify_license': ''
    }
    if not is_community():
        inputs['cloudify_license'] = yaml.load(get_resource_path(
            'test_valid_paying_license.yaml'
        ))
    package_tester.template_inputs['cloudify_license'] = \
        inputs['cloudify_license']
    package_tester.run_test(inputs)


class _OSXCliPackageTester(object):

    def __init__(self, *args):
        super(_OSXCliPackageTester, self).__init__(*args)
        self.template_inputs = {}

    def _copy_terraform_files(self):
        self._generate_terraform_file()
        shutil.copy(get_resource_path(
            'terraform/scripts/osx-cli-test.sh'),
            self.tmpdir / 'scripts/osx-cli-test.sh')

    def _generate_terraform_file(self):
        terraform_template_file = self.tmpdir / 'aws-osx-cli-test.tf'
        input_file = get_resource_path(
            'terraform/{0}'.format('aws-osx-cli-test.tf.template')
        )
        with open(input_file, 'r') as f:
            tf_template = f.read()

        output = jinja2.Template(tf_template).render(self.template_inputs)
        terraform_template_file.write_text(output)
