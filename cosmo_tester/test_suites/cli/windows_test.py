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


import time

import pytest

from cosmo_tester.framework.util import (
    get_attributes,
    get_cli_package_url,
)
from cosmo_tester.framework.test_hosts import (
    get_image,
    REMOTE_PRIVATE_KEY_PATH,
    TestHosts as Hosts,
)


def get_windows_image_settings():
    attrs = get_attributes()
    return [
        (attrs.windows_2012_image_name, attrs.windows_2012_username,
         'windows_cli_package_url'),
    ]


@pytest.fixture(
    scope='module',
    params=get_windows_image_settings())
def windows_cli_tester(request, cfy, ssh_key, module_tmpdir, attributes,
                       logger):

    cli_hosts = Hosts(
        cfy, ssh_key, module_tmpdir,
        attributes, logger, 2, request=request, upload_plugins=False,
    )
    cli_hosts.instances[0] = get_image('centos')
    cli_hosts.instances[0].prepare_for_windows(request.param[0],
                                               request.param[1])
    cli_hosts.create()

    cli_hosts.instances[0].wait_for_winrm()

    try:
        yield {
            'instances': cli_hosts.instances,
            'username': request.param[1],
            'url_key': request.param[2],
        }
    finally:
        cli_hosts.destroy()


def test_cli_on_windows_2012(windows_cli_tester, logger):
    cli_host, manager_host = windows_cli_tester['instances']
    username = windows_cli_tester['username']
    url_key = windows_cli_tester['url_key']

    logger.info('CLI server id is: %s', cli_host.server_id)

    work_dir = 'C:\\Users\\{0}'.format(username)
    cli_installer_exe_name = 'cloudify-cli.exe'
    cli_installer_exe_path = '{0}\\{1}'.format(work_dir,
                                               cli_installer_exe_name)
    cfy_exe = 'C:\\Cloudify\\embedded\\Scripts\\cfy.exe'

    logger.info('Downloading CLI package..')
    cli_package_url = get_cli_package_url(url_key)
    cli_host.run_windows_command(
        """
$client = New-Object System.Net.WebClient
$url = "{0}"
$file = "{1}"
$client.DownloadFile($url, $file)""".format(
            cli_package_url,
            cli_installer_exe_path
        ),
        powershell=True,
    )

    logger.info('Installing CLI...')
    logger.info('Using CLI package: {url}'.format(
        url=cli_package_url,
    ))
    cli_host.run_windows_command(
        '''
cd {0}
& .\\{1} /SILENT /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\\Cloudify"'''
        .format(work_dir, cli_installer_exe_name),
        powershell=True,
    )

    logger.info('Testing cloudify manager...')
    cli_host.run_windows_command(
        '{cfy} profiles use {ip} -u admin -p admin -t default_tenant'
        .format(cfy=cfy_exe, ip=manager_host.ip_address),
    )
    cli_host.run_windows_command(
        (
            '{cfy} blueprints upload {hello_world} -b bp '
            '-n singlehost-blueprint.yaml'.format(
                cfy=cfy_exe,
                hello_world='cloudify-cosmo/cloudify-hello-world-example',
            )
        ),
    )
    cli_host.run_windows_command(
        (
            '{cfy} deployments create -b bp dep '
            '-i server_ip={ip} '
            '-i agent_user={agent_user} '
            '-i agent_private_key_path={key_path}'.format(
                cfy=cfy_exe,
                ip=manager_host.private_ip_address,
                agent_user=get_attributes()['default_linux_username'],
                key_path=REMOTE_PRIVATE_KEY_PATH,
            )
        ),
    )
    cli_host.run_windows_command(
        '{cfy} executions start install -d dep'.format(cfy=cfy_exe),
    )

    cli_host.run_windows_command(
        '''
$url=Invoke-WebRequest -URI http://{ip}:8080 -UseBasicParsing
$url.ToString() | select-string "Hello, World"
'''.format(ip=manager_host.private_ip_address),
        powershell=True,
    )

    cli_host.run_windows_command(
        '{cfy} executions start uninstall -d dep'.format(cfy=cfy_exe),
    )
    cli_host.run_windows_command(
        '{cfy} deployments delete dep'.format(cfy=cfy_exe),
    )
    # Depoyment is deleted from DB AFTER delete_dep_env workflow ended
    #  successfully, this might take a second or two
    time.sleep(4)
    cli_host.run_windows_command(
        '{cfy} blueprints delete bp'.format(cfy=cfy_exe),
    )
