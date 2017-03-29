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


import json
import os
import sh
import shutil
import uuid

from path import Path
import pytest

from cosmo_tester.framework import util


def _get_cli_package_url(name):
    urls = util.get_cli_package_urls()
    return urls['cli_premium_packages_urls'][name]


class _CliPackageTester(object):

    def __init__(self, tmpdir, inputs, logger):
        self.terraform = util.sh_bake(sh.terraform)
        self.tmpdir = tmpdir
        self.inputs = inputs
        self.logger = logger
        self.inputs_file = self.tmpdir / 'inputs.json'
        self.windows = False

    def _copy_terraform_files(self):
        os.mkdir(self.tmpdir / 'scripts')
        if self.windows:
            shutil.copy(util.get_resource_path(
                    'terraform/openstack-windows-cli-test.tf'),
                    self.tmpdir / 'openstack-windows-cli-test.tf')
            shutil.copy(util.get_resource_path(
                    'terraform/scripts/windows-cli-test.ps1'),
                    self.tmpdir / 'scripts/windows-cli-test.ps1')
            shutil.copy(util.get_resource_path(
                    'terraform/scripts/windows-userdata.ps1'),
                    self.tmpdir / 'scripts/windows-userdata.ps1')
        else:
            shutil.copy(util.get_resource_path(
                    'terraform/openstack-linux-cli-test.tf'),
                    self.tmpdir / 'openstack-linux-cli-test.tf')
            shutil.copy(util.get_resource_path(
                    'terraform/scripts/linux-cli-test.sh'),
                    self.tmpdir / 'scripts/linux-cli-test.sh')

    def run_test(self):
        self._copy_terraform_files()
        self.inputs_file.write_text(json.dumps(self.inputs, indent=2))
        self.logger.info('Testing CLI package..')
        with self.tmpdir:
            self.terraform.apply(['-var-file', self.inputs_file])

    def perform_cleanup(self):
        self.logger.info('Performing cleanup..')
        with self.tmpdir:
            self.terraform.destroy(['-var-file', self.inputs_file, '-force'])


@pytest.fixture(scope='function')
def cli_package_tester(ssh_key, attributes, tmpdir, logger):
    logger.info('Using temp dir: %s', tmpdir)
    tmpdir = Path(tmpdir)

    tf_inputs = {
        'resource_suffix': str(uuid.uuid4()),
        'public_key_path': ssh_key.public_key_path,
        'private_key_path': ssh_key.private_key_path,
        'cli_flavor': attributes.small_flavor_name,
        'manager_flavor': attributes.large_flavor_name,
    }

    tester = _CliPackageTester(tmpdir, tf_inputs, logger)

    yield tester

    tester.perform_cleanup()


@pytest.mark.skip(reason='Currently skipped due to Jenkins env limitation')
def test_cli_on_centos_7(cli_package_tester, attributes):
    cli_package_tester.inputs.update({
        'cli_image': attributes.centos7_image_name,
        'cli_user': attributes.centos7_username,
        'manager_image': attributes.centos7_image_name,
        'manager_user': attributes.centos7_username,
        'cli_package_url': _get_cli_package_url('rhel_centos_cli_package_url')
    })
    cli_package_tester.run_test()


@pytest.mark.skip(reason='Currently skipped due to Jenkins env limitation')
def test_cli_on_centos_6(cli_package_tester, attributes):
    cli_package_tester.inputs.update({
        'cli_image': attributes.centos6_image_name,
        'cli_user': attributes.centos6_username,
        'manager_image': attributes.centos7_image_name,
        'manager_user': attributes.centos7_username,
        'cli_package_url': _get_cli_package_url('rhel_centos_cli_package_url')
    })
    cli_package_tester.run_test()


@pytest.mark.skip(reason='Currently skipped due to OpenStack env limitation')
def test_cli_on_windows_2012(cli_package_tester, attributes):
    cli_package_tester.windows = True
    cli_package_tester.inputs.update({
        'cli_image': attributes.windows_server_2012_image_name,
        'cli_user': attributes.windows_server_2012_username,
        'manager_image': attributes.centos7_image_name,
        'manager_user': attributes.centos7_username,
        'cli_flavor': attributes.medium_flavor_name,
        'cli_package_url': _get_cli_package_url('rhel_centos_cli_package_url')
    })
    cli_package_tester.run_test()
