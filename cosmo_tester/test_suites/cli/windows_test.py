import json

import pytest

from cosmo_tester.framework.util import get_cli_package_url
from cosmo_tester.framework.test_hosts import (
    get_image,
    Hosts,
)
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.cli import (
    _prepare,
    _test_cfy_install,
    _test_teardown,
    _test_upload_and_install,
    get_image_and_username,
)


def test_cli_deployment_flow_windows(windows_cli_tester, logger):
    cli_host = windows_cli_tester['cli_host']
    example = windows_cli_tester['example']
    paths = windows_cli_tester['paths']

    _prepare(cli_host.run_windows_command, example, paths, logger)

    _test_upload_and_install(
        cli_host.run_windows_command, example, paths, logger)

    _test_teardown(cli_host.run_windows_command, example, paths, logger)


def test_cli_install_flow_windows(windows_cli_tester, logger):
    cli_host = windows_cli_tester['cli_host']
    example = windows_cli_tester['example']
    paths = windows_cli_tester['paths']

    _prepare(cli_host.run_windows_command, example, paths, logger)

    _test_cfy_install(cli_host.run_windows_command, example, paths, logger)

    _test_teardown(cli_host.run_windows_command, example, paths, logger)


def get_windows_image_settings():
    return [
        ('windows_2012', 'windows_cli_package_url'),
    ]


@pytest.fixture(
    scope='module',
    params=get_windows_image_settings())
def windows_cli_tester(request, ssh_key, module_tmpdir, test_config,
                       logger):

    _, username = get_image_and_username(request.param[0], test_config)

    cli_hosts = Hosts(
        ssh_key, module_tmpdir,
        test_config, logger, request, 2,
    )
    cli_hosts.instances[0] = get_image('centos', test_config)
    cli_hosts.instances[0].prepare_for_windows(request.param[0])

    passed = True

    try:
        cli_hosts.create()
        cli_hosts.instances[0].wait_for_winrm()

        url_key = request.param[1]
        cli_host, manager_host = cli_hosts.instances

        work_dir = 'C:\\Users\\{0}'.format(username)
        cli_installer_exe_name = 'cloudify-cli.exe'
        cli_installer_exe_path = '{0}\\{1}'.format(work_dir,
                                                   cli_installer_exe_name)

        logger.info('Downloading CLI package')
        cli_package_url = get_cli_package_url(url_key, test_config)
        logger.info('Using CLI package: {url}'.format(
            url=cli_package_url,
        ))
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
        cli_host.run_windows_command(
            '''
    cd {0}
    & .\\{1} /SILENT /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\\Cloudify"'''
            .format(work_dir, cli_installer_exe_name),
            powershell=True,
        )

        example = get_example_deployment(
            manager_host, ssh_key, logger, url_key, test_config)
        example.use_windows(cli_host.username, cli_host.password)
        example.inputs['path'] = '/tmp/{}'.format(url_key)

        logger.info('Copying blueprint to CLI host')
        remote_blueprint_path = work_dir + '\\Documents\\blueprint.yaml'
        with open(example.blueprint_file) as blueprint_handle:
            blueprint = blueprint_handle.read()
        cli_host.put_windows_remote_file_content(remote_blueprint_path,
                                                 blueprint)

        logger.info('Copying inputs to CLI host')
        remote_inputs_path = work_dir + '\\Documents\\inputs.yaml'
        cli_host.put_windows_remote_file_content(remote_inputs_path,
                                                 json.dumps(example.inputs))

        logger.info('Copying agent ssh key to CLI host for secret')
        remote_ssh_key_path = work_dir + '\\Documents\\ssh_key.pem'
        with open(ssh_key.private_key_path) as ssh_key_handle:
            ssh_key_data = ssh_key_handle.read()
        cli_host.put_windows_remote_file_content(remote_ssh_key_path,
                                                 ssh_key_data)

        yield {
            'cli_host': cli_host,
            'example': example,
            'paths': {
                'blueprint': remote_blueprint_path,
                'inputs': remote_inputs_path,
                'ssh_key': remote_ssh_key_path,
                'cfy': 'C:\\Cloudify\\embedded\\Scripts\\cfy.exe',
            },
        }
    except Exception:
        passed = False
        raise
    finally:
        cli_hosts.destroy(passed=passed)
