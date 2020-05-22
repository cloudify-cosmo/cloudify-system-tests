import json
import os

import pytest

from cosmo_tester.framework.util import (
    get_cli_package_url,
    get_resource_path,
)
from cosmo_tester.framework.test_hosts import (
    get_image,
    Hosts,
)
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.cli import get_image_and_username


def get_linux_image_settings():
    return [
        ('centos_7', 'rhel_centos_cli_package_url'),
        ('ubuntu_14_04', 'debian_cli_package_url'),
        ('rhel_7', 'rhel_centos_cli_package_url'),
    ]


@pytest.fixture(
    scope='module',
    params=get_linux_image_settings())
def linux_cli_tester(request, cfy, ssh_key, module_tmpdir, test_config,
                     logger, install_dev_tools=True):
    instances = [
        get_image('centos', test_config),
        get_image('master', test_config),
    ]

    image, username = get_image_and_username(request.param[0], test_config)
    instances[0].image_name = image
    instances[0].username = username

    cli_hosts = Hosts(
        cfy, ssh_key, module_tmpdir,
        test_config, logger, request, instances=instances,
    )

    passed = True

    try:
        cli_hosts.create()

        yield {
            'cli_hosts': cli_hosts,
            'username': instances[1].username,
            'url_key': request.param[1],
        }
    except Exception:
        passed = False
        raise
    finally:
        cli_hosts.destroy(passed=passed)


def test_cli_on_linux(linux_cli_tester, module_tmpdir, ssh_key, logger,
                      test_config):
    cli_host, manager_host = linux_cli_tester['cli_hosts'].instances

    local_install_script_path = get_resource_path(
        'scripts/linux-cli-test-install'
    )
    remote_install_script_path = '/tmp/linux-cli-test-install'
    cli_host.put_remote_file(
        remote_path=remote_install_script_path,
        local_path=local_install_script_path,
    )
    cli_host.run_command('chmod 500 {}'.format(remote_install_script_path))

    local_uninstall_script_path = get_resource_path(
        'scripts/linux-cli-test-uninstall'
    )
    remote_uninstall_script_path = '/tmp/linux-cli-test-uninstall'
    cli_host.put_remote_file(
        remote_path=remote_uninstall_script_path,
        local_path=local_uninstall_script_path,
    )
    cli_host.run_command('chmod 500 {}'.format(remote_uninstall_script_path))

    example = get_example_deployment(
        manager_host, ssh_key, logger, linux_cli_tester['url_key'],
        test_config)
    example.set_agent_key_secret()
    example.inputs['path'] = '/tmp/{}'.format(linux_cli_tester['url_key'])
    cli_host.run_command('mkdir -p /tmp/test_blueprint')
    cli_host.put_remote_file(
        remote_path='/tmp/test_blueprint/blueprint.yaml',
        local_path=example.blueprint_file,
    )
    local_inputs_path = os.path.join(
        module_tmpdir, linux_cli_tester['url_key'] + '_inputs.yaml',
    )
    with open(local_inputs_path, 'w') as inputs_handle:
        inputs_handle.write(json.dumps(example.inputs))
    cli_host.put_remote_file(
        remote_path='/tmp/test_blueprint/inputs.yaml',
        local_path=local_inputs_path,
    )

    cli_host.run_command(
        '{script} {cli_url} {mgr_priv} {tenant}'.format(
            script=remote_install_script_path,
            cli_url=get_cli_package_url(linux_cli_tester['url_key'],
                                        test_config),
            mgr_priv=manager_host.private_ip_address,
            tenant=example.tenant,
        )
    )
    example.check_files()

    cli_host.run_command(remote_uninstall_script_path)
    example.check_all_test_files_deleted()
