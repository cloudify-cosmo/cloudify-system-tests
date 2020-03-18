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
import time

import shutil

from path import Path
import pytest
import retrying
import winrm

from cosmo_tester.framework.util import (
    AttributesDict,
    get_cli_package_url,
    get_openstack_server_password,
    get_resource_path,
)

WINRM_PORT = 5985


@pytest.fixture(scope='function')
def package_tester(request, ssh_key, attributes, tmpdir, logger):
    _package_tester_mapping = {
        'windows': _WindowsCliPackageTester
    }
    platform = request.param
    tester_class = _package_tester_mapping[platform]

    logger.info('Using temp dir: %s', tmpdir)
    tmpdir = Path(tmpdir)

    tester = tester_class(tmpdir, attributes, ssh_key, logger)

    yield tester

    tester.perform_cleanup()


@pytest.mark.parametrize('package_tester', ['windows'], indirect=True)
def _test_cli_on_windows_2012(package_tester, attributes):
    inputs = {
        'cli_image': attributes.windows_2012_image_name,
        'cli_user': attributes.windows_2012_username,
        'manager_user': attributes.default_linux_username,
        'cli_flavor': attributes.medium_flavor_name,
    }
    package_tester.run_test(inputs)


class _WindowsCliPackageTester(object):
    """A separate class for testing Windows CLI package bootstrap.

    Since it is impossible to retrieve a Windows VM password from OpenStack
    using terraform, we first run terraform for creating two VMs: Linux for
    the manager and Windows for CLI.

    Once the Windows machine is up, an OpenStack client is used in order
    to retrieve the VMs password. Then the terraform template is updated
    with the extra resources needed for performing bootstrap (including
    the retrieved password).
    """

    def __init__(self, tmpdir, attributes, ssh_key, logger):
        super(_WindowsCliPackageTester, self).__init__(tmpdir, attributes,
                                                       ssh_key, logger)
        self._session = None
        self._outputs = None

    def _copy_terraform_files(self):
        shutil.copy(get_resource_path(
                'terraform/openstack-windows-cli-test.tf'),
                self.tmpdir / 'openstack-windows-cli-test.tf')
        shutil.copy(get_resource_path(
                'terraform/scripts/windows-userdata.ps1'),
                    self.tmpdir / 'scripts/windows-userdata.ps1')

    @retrying.retry(stop_max_attempt_number=30, wait_fixed=10000)
    def get_password(self, server_id):
        self.logger.info(
                'Waiting for VM password retrieval.. [server_id=%s]',
                server_id)
        password = get_openstack_server_password(
                server_id, self.ssh_key.private_key_path)
        assert password is not None and len(password) > 0
        return password

    def _run_cmd(self, cmd, powershell=False):
        self.logger.info('Running command: %s', cmd)
        if powershell:
            r = self._session.run_ps(cmd)
        else:
            r = self._session.run_cmd(cmd)
        self.logger.info('- stdout: %s', r.std_out)
        self.logger.info('- stderr: %s', r.std_err)
        self.logger.info('- status_code: %d', r.status_code)
        assert r.status_code == 0

    def _calculate_outputs(self):
        with self.tmpdir:
            self._outputs = AttributesDict(
                    {k: v['value'] for k, v in json.loads(
                            self.terraform.output(
                                    ['-json']).stdout).items()})

    def _set_winrm_session(self):
        # Retrieve password from OpenStack
        password = self.get_password(self._outputs.cli_server_id)
        self.logger.info('VM password: %s', password)
        self.inputs['password'] = password

        url = 'http://{0}:{1}/wsman'.format(
            self._outputs.cli_public_ip_address,
            WINRM_PORT)
        user = self.inputs['cli_user']
        self._session = winrm.Session(url, auth=(user, password))

    def run_test(self, inputs):
        super(_WindowsCliPackageTester, self).run_test(inputs)
        # At this stage, there are two VMs (Windows & Linux).

        self._calculate_outputs()
        self.logger.info('CLI server id is: %s', self._outputs.cli_server_id)

        self._set_winrm_session()

        with open(self.ssh_key.private_key_path, 'r') as f:
            private_key = f.read()

        work_dir = 'C:\\Users\\{0}'.format(self.inputs['cli_user'])
        remote_private_key_path = '{0}\\ssh_key.pem'.format(work_dir)
        cli_installer_exe_name = 'cloudify-cli.exe'
        cli_installer_exe_path = '{0}\\{1}'.format(work_dir,
                                                   cli_installer_exe_name)
        cfy_exe = 'C:\\Cloudify\\embedded\\Scripts\\cfy.exe'

        self.logger.info('Uploading private key to Windows VM..')
        self._run_cmd('''
Set-Content "{0}" "{1}"
'''.format(remote_private_key_path, private_key), powershell=True)

        self.logger.info('Downloading CLI package..')
        cli_package_url = get_cli_package_url('windows_cli_package_url')
        self._run_cmd("""
$client = New-Object System.Net.WebClient
$url = "{0}"
$file = "{1}"
$client.DownloadFile($url, $file)""".format(
                cli_package_url,
                cli_installer_exe_path), powershell=True)

        self.logger.info('Installing CLI...')
        self.logger.info('Using CLI package: {url}'.format(
            url=cli_package_url,
        ))
        self._run_cmd('''
cd {0}
& .\\{1} /SILENT /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\\Cloudify"'''
                      .format(work_dir, cli_installer_exe_name),
                      powershell=True)

        self.logger.info('Testing cloudify manager...')
        self._run_cmd(
            '{cfy} profiles use {ip} -u admin -p admin -t default_tenant'
            ''.format(cfy=cfy_exe, ip=self._outputs.manager_private_ip_address)
        )
        self._run_cmd(
            '{cfy} blueprints upload {hello_world} -b bp '
            '-n singlehost-blueprint.yaml'.format(
                cfy=cfy_exe,
                hello_world='cloudify-cosmo/cloudify-hello-world-example'
            )
        )
        self._run_cmd(
            '{cfy} deployments create -b bp dep '
            '-i server_ip={ip} '
            '-i agent_user={agent_user} '
            '-i agent_private_key_path={key_path}'.format(
                cfy=cfy_exe,
                ip=self._outputs.manager_private_ip_address,
                agent_user=self.inputs['manager_user'],
                key_path=self.inputs['remote_key_path']
            )
        )
        self._run_cmd('{cfy} executions start install -d dep'.format(
            cfy=cfy_exe
        ))

        self._run_cmd('''
$url=Invoke-WebRequest -URI http://{ip}:8080 -UseBasicParsing
$url.ToString() | select-string "Hello, World"
'''.format(ip=self._outputs.manager_private_ip_address), powershell=True)

        self._run_cmd('{cfy} executions start uninstall -d dep'.format(
            cfy=cfy_exe
        ))
        self._run_cmd('{cfy} deployments delete dep'.format(cfy=cfy_exe))
        # Depoyment is deleted from DB AFTER delete_dep_env workflow ended
        #  successfully, this might take a second or two
        time.sleep(4)
        self._run_cmd('{cfy} blueprints delete bp'.format(cfy=cfy_exe))
