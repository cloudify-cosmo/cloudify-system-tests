import json
import pytest

from cosmo_tester.framework.test_hosts import Hosts, VM
from cosmo_tester.framework.examples import get_example_deployment

from . import _install_linux_cli, get_linux_image_settings


@pytest.fixture(
    scope='module',
    params=get_linux_image_settings())
def linux_cli_tester(request, ssh_key, module_tmpdir, test_config,
                     logger, install_dev_tools=True):
    instances = [
        VM('centos_7', test_config),
        VM('master', test_config),
    ]

    cli_hosts = Hosts(
        ssh_key, module_tmpdir,
        test_config, logger, request, instances=instances,
    )

    passed = True

    try:
        cli_hosts.create()

        url_key = request.param[1]
        pkg_type = request.param[2]
        cli_host, manager_host = cli_hosts.instances

        _install_linux_cli(cli_host, logger, url_key, pkg_type, test_config)

        example = get_example_deployment(
            manager_host, ssh_key, logger, url_key, test_config)
        example.inputs['path'] = '/tmp/{}'.format(url_key)

        logger.info('Copying blueprint to CLI host')
        cli_host.run_command('mkdir -p /tmp/test_blueprint')
        remote_blueprint_path = '/tmp/test_blueprint/blueprint.yaml'
        cli_host.put_remote_file(
            remote_path=remote_blueprint_path,
            local_path=example.blueprint_file,
        )

        logger.info('Copying inputs to CLI host')
        remote_inputs_path = '/tmp/test_blueprint/inputs.yaml'
        cli_host.put_remote_file_content(
            remote_path=remote_inputs_path,
            content=json.dumps(example.inputs),
        )

        logger.info('Copying agent ssh key to CLI host for secret')
        remote_ssh_key_path = '/tmp/cli_test_ssh_key.pem'
        cli_host.put_remote_file(
            remote_path=remote_ssh_key_path,
            local_path=ssh_key.private_key_path,
        )

        yield {
            'cli_host': cli_host,
            'example': example,
            'paths': {
                'blueprint': remote_blueprint_path,
                'inputs': remote_inputs_path,
                'ssh_key': remote_ssh_key_path,
                # Expected to be in path on linux systems
                'cfy': 'cfy',
                'cert': '/home/{user}/manager.crt'.format(
                    user=cli_host.username),
            },
        }
    except Exception:
        passed = False
        raise
    finally:
        cli_hosts.destroy(passed=passed)
