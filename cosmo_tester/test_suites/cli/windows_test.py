import json
import time

import pytest

from cosmo_tester.framework.util import get_cli_package_url
from cosmo_tester.framework.test_hosts import (
    get_image,
    Hosts,
)
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.cli import get_image_and_username


def get_windows_image_settings():
    return [
        ('windows_2012', 'windows_cli_package_url'),
    ]


@pytest.fixture(
    scope='module',
    params=get_windows_image_settings())
def windows_cli_tester(request, cfy, ssh_key, module_tmpdir, test_config,
                       logger):

    image, username = get_image_and_username(request.param[0], test_config)

    cli_hosts = Hosts(
        cfy, ssh_key, module_tmpdir,
        test_config, logger, request, 2, upload_plugins=False,
    )
    cli_hosts.instances[0] = get_image('centos')
    cli_hosts.instances[0].prepare_for_windows(image,
                                               username)
    cli_hosts.create()

    cli_hosts.instances[0].wait_for_winrm()

    passed = True

    try:
        yield {
            'instances': cli_hosts.instances,
            'username': username,
            'url_key': request.param[1],
        }
    except Exception:
        passed = False
        raise
    finally:
        cli_hosts.destroy(passed=passed)


def test_cli_on_windows_2012(windows_cli_tester, logger, ssh_key,
                             test_config):
    cli_host, manager_host = windows_cli_tester['instances']
    username = windows_cli_tester['username']
    url_key = windows_cli_tester['url_key']

    logger.info('CLI server id is: %s', cli_host.server_id)

    work_dir = 'C:\\Users\\{0}'.format(username)
    cli_installer_exe_name = 'cloudify-cli.exe'
    cli_installer_exe_path = '{0}\\{1}'.format(work_dir,
                                               cli_installer_exe_name)

    example = get_example_deployment(
        manager_host, ssh_key, logger, windows_cli_tester['url_key'],
        test_config)
    example.use_windows()
    example.inputs['path'] = '/tmp/{}'.format(windows_cli_tester['url_key'])
    remote_blueprint_path = work_dir + '\\Documents\\blueprint.yaml'
    remote_inputs_path = work_dir + '\\Documents\\inputs.yaml'
    with open(example.blueprint_file) as blueprint_handle:
        blueprint = blueprint_handle.read()
    cli_host.put_windows_remote_file_content(remote_blueprint_path, blueprint)
    cli_host.put_windows_remote_file_content(remote_inputs_path,
                                             json.dumps(example.inputs))

    cfy_exe = 'C:\\Cloudify\\embedded\\Scripts\\cfy.exe'

    logger.info('Downloading CLI package..')
    cli_package_url = get_cli_package_url(url_key, test_config)
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
        '{cfy} profiles use {ip} -u admin -p admin -t {tenant}'
        .format(cfy=cfy_exe, ip=manager_host.ip_address,
                tenant=example.tenant),
    )
    cli_host.run_windows_command(
        (
            '{cfy} blueprints upload -b test_bp {blueprint_path}'.format(
                cfy=cfy_exe,
                blueprint_path=remote_blueprint_path,
            )
        ),
    )
    cli_host.run_windows_command(
        '{cfy} deployments create -b test_bp -i {inputs} test_dep '.format(
            cfy=cfy_exe,
            inputs=remote_inputs_path
        ),
    )
    cli_host.run_windows_command(
        '{cfy} executions start install -d test_dep'.format(cfy=cfy_exe),
    )

    example.check_files()

    cli_host.run_windows_command(
        '{cfy} executions start uninstall -d test_dep'.format(cfy=cfy_exe),
    )
    cli_host.run_windows_command(
        '{cfy} deployments delete test_dep'.format(cfy=cfy_exe),
    )
    # Depoyment is deleted from DB AFTER delete_dep_env workflow ended
    #  successfully, this might take a second or two
    time.sleep(4)
    cli_host.run_windows_command(
        '{cfy} blueprints delete test_bp'.format(cfy=cfy_exe),
    )
    example.check_all_test_files_deleted()
