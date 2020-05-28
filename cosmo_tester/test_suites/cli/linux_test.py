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


def test_cli_deployment_flow_linux(linux_cli_tester, logger):
    cli_host = linux_cli_tester['cli_host']
    example = linux_cli_tester['example']
    paths = linux_cli_tester['paths']

    _prepare(cli_host.run_command, example, paths, logger)

    _test_upload_and_install(cli_host.run_command, example, paths, logger)

    _test_teardown(cli_host.run_command, example, paths, logger)


def test_cli_install_flow_linux(linux_cli_tester, logger):
    cli_host = linux_cli_tester['cli_host']
    example = linux_cli_tester['example']
    paths = linux_cli_tester['paths']

    _prepare(cli_host.run_command, example, paths, logger)

    _test_cfy_install(cli_host.run_command, example, paths, logger)

    _test_teardown(cli_host.run_command, example, paths, logger)


def get_linux_image_settings():
    return [
        ('centos_7', 'rhel_centos_cli_package_url', 'rpm'),
        ('ubuntu_14_04', 'debian_cli_package_url', 'deb'),
        ('rhel_7', 'rhel_centos_cli_package_url', 'rpm'),
    ]


@pytest.fixture(
    scope='module',
    params=get_linux_image_settings())
def linux_cli_tester(request, ssh_key, module_tmpdir, test_config,
                     logger, install_dev_tools=True):
    instances = [
        get_image('centos', test_config),
        get_image('master', test_config),
    ]

    image, username = get_image_and_username(request.param[0], test_config)
    instances[0].image_name = image
    instances[0].username = username

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

        logger.info('Downloading CLI package')
        cli_package_url = get_cli_package_url(linux_cli_tester['url_key'],
                                              test_config)
        logger.info('Using CLI package: {url}'.format(
            url=cli_package_url,
        ))
        cli_host.run_command('wget {url} -O cloudify-cli.{pkg_type}'.format(
            url=cli_package_url, pkg_type=pkg_type,
        ))

        logger.info('Installing CLI package')
        install_cmd = {
            'rpm': 'rpm',
            'deb': 'dpkg',
        }[pkg_type]
        cli_host.run_command(
            '{install_cmd} -i cloudify-cli.{pkg_type}'.format(
                install_cmd=install_cmd,
                pkg_type=pkg_type,
            ),
            use_sudo=True,
        )

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
            },
        }
    except Exception:
        passed = False
        raise
    finally:
        cli_hosts.destroy(passed=passed)
