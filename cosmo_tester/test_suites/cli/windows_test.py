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

import retrying
import pytest
import winrm

from cosmo_tester.framework.util import (
    get_attributes,
    get_cli_package_url,
)
from cosmo_tester.framework.test_hosts import (
    get_image,
    REMOTE_PRIVATE_KEY_PATH,
    TestHosts,
)

WINRM_PORT = 5985


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
                       logger, install_dev_tools=True):
    instances = [
        get_image('centos'),
        get_image('master'),
    ]

    add_firewall_cmd = "&netsh advfirewall firewall add rule"
    password = 'AbCdEfG123456!'

    instances[0].image_name = request.param[0]
    instances[0].enable_ssh_wait = False
    instances[0].userdata = """#ps1_sysnative
$PSDefaultParameterValues['*:Encoding'] = 'utf8'

Write-Host "## Configuring WinRM and firewall rules.."
winrm quickconfig -q
winrm set winrm/config              '@{{MaxTimeoutms="1800000"}}'
winrm set winrm/config/winrs        '@{{MaxMemoryPerShellMB="300"}}'
winrm set winrm/config/service      '@{{AllowUnencrypted="true"}}'
winrm set winrm/config/service/auth '@{{Basic="true"}}'
{fw_cmd} name="WinRM 5985" protocol=TCP dir=in localport=5985 action=allow
{fw_cmd} name="WinRM 5986" protocol=TCP dir=in localport=5986 action=allow

Write-Host "## Setting password for Admin user.."
$user = [ADSI]"WinNT://localhost/{user}"
$user.SetPassword("{password}")
$user.SetInfo()""".format(fw_cmd=add_firewall_cmd,
                          user=request.param[1],
                          password=password)

    cli_hosts = TestHosts(
        cfy, ssh_key, module_tmpdir,
        attributes, logger, instances=instances, request=request,
        upload_plugins=False,
    )
    cli_hosts.create()

    wait_for_winrm(instances[0], request.param[1], password, logger)

    yield {
        'cli_hosts': cli_hosts,
        'username': request.param[1],
        'password': password,
        'url_key': request.param[2],
    }
    cli_hosts.destroy()


def test_cli_on_windows_2012(windows_cli_tester, logger):
    cli_host, manager_host = windows_cli_tester['cli_hosts'].instances
    username = windows_cli_tester['username']
    password = windows_cli_tester['password']
    url_key = windows_cli_tester['url_key']

    logger.info('CLI server id is: %s', cli_host.server_id)

    session = get_winrm_session(username,
                                password,
                                cli_host.ip_address)

    work_dir = 'C:\\Users\\{0}'.format(username)
    cli_installer_exe_name = 'cloudify-cli.exe'
    cli_installer_exe_path = '{0}\\{1}'.format(work_dir,
                                               cli_installer_exe_name)
    cfy_exe = 'C:\\Cloudify\\embedded\\Scripts\\cfy.exe'

    logger.info('Downloading CLI package..')
    cli_package_url = get_cli_package_url(url_key)
    run_cmd(
        session=session,
        cmd="""
$client = New-Object System.Net.WebClient
$url = "{0}"
$file = "{1}"
$client.DownloadFile($url, $file)""".format(
            cli_package_url,
            cli_installer_exe_path
        ),
        logger=logger,
        powershell=True,
    )

    logger.info('Installing CLI...')
    logger.info('Using CLI package: {url}'.format(
        url=cli_package_url,
    ))
    run_cmd(
        session=session,
        cmd='''
cd {0}
& .\\{1} /SILENT /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\\Cloudify"'''
        .format(work_dir, cli_installer_exe_name),
        logger=logger,
        powershell=True,
    )

    logger.info('Testing cloudify manager...')
    run_cmd(
        session=session,
        cmd='{cfy} profiles use {ip} -u admin -p admin -t default_tenant'
        .format(cfy=cfy_exe, ip=manager_host.ip_address),
        logger=logger,
    )
    run_cmd(
        session=session,
        cmd=(
            '{cfy} blueprints upload {hello_world} -b bp '
            '-n singlehost-blueprint.yaml'.format(
                cfy=cfy_exe,
                hello_world='cloudify-cosmo/cloudify-hello-world-example',
            )
        ),
        logger=logger,
    )
    run_cmd(
        session=session,
        cmd=(
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
        logger=logger,
    )
    run_cmd(
        session=session,
        cmd='{cfy} executions start install -d dep'.format(cfy=cfy_exe),
        logger=logger,
    )

    run_cmd(
        session=session,
        cmd='''
$url=Invoke-WebRequest -URI http://{ip}:8080 -UseBasicParsing
$url.ToString() | select-string "Hello, World"
'''.format(ip=manager_host.private_ip_address),
        logger=logger,
        powershell=True,
    )

    run_cmd(
        session=session,
        cmd='{cfy} executions start uninstall -d dep'.format(cfy=cfy_exe),
        logger=logger,
    )
    run_cmd(
        session=session,
        cmd='{cfy} deployments delete dep'.format(cfy=cfy_exe),
        logger=logger,
    )
    # Depoyment is deleted from DB AFTER delete_dep_env workflow ended
    #  successfully, this might take a second or two
    time.sleep(4)
    run_cmd(
        session=session,
        cmd='{cfy} blueprints delete bp'.format(cfy=cfy_exe),
        logger=logger,
    )


def run_cmd(session, cmd, logger, powershell=False):
    logger.info('Running command: %s', cmd)
    runner = session.run_ps if powershell else session.run_cmd

    result = runner(cmd)

    logger.info('- stdout: %s', result.std_out)
    logger.info('- stderr: %s', result.std_err)
    logger.info('- status_code: %d', result.status_code)
    assert result.status_code == 0


def get_winrm_session(username, password, ip):
    url = 'http://{0}:{1}/wsman'.format(ip, WINRM_PORT)
    return winrm.Session(url, auth=(username, password))


@retrying.retry(stop_max_attempt_number=120, wait_fixed=3000)
def wait_for_winrm(instance, username, password, logger):
    logger.info('Checking Windows VM %s is up...', instance.ip_address)
    session = get_winrm_session(username,
                                password,
                                instance.ip_address)
    run_cmd(
        session=session,
        cmd='Write-Output "Testing winrm."',
        logger=logger,
        powershell=True,
    )
    logger.info('...Windows VM is up.')
