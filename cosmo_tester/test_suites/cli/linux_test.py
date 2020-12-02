import json
import pytest
import hashlib
import tarfile
import tempfile
from pathlib import Path

from cosmo_tester.framework.util import get_cli_package_url
from cosmo_tester.framework.test_hosts import (
    get_image,
    Hosts,
)
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.cli import (
    _prepare,
    _test_cfy_install,
    _test_cfy_logs,
    _test_teardown,
    _test_upload_and_install,
    get_image_and_username,
)
from cosmo_tester.test_suites.cluster.conftest import _get_hosts


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
        ('rhel_7', 'rhel_centos_cli_package_url', 'rpm'),
    ]


def test_cfy_logs_linux(linux_cli_tester, logger):
    cli_host = linux_cli_tester['cli_host']
    example = linux_cli_tester['example']
    paths = linux_cli_tester['paths']

    _prepare(cli_host.run_command, example, paths, logger)
    _test_cfy_logs(cli_host.run_command, cli_host, example, paths, logger)


def test_cfy_logs_linux_cluster(linux_cluster_cli_tester, logger):
    cli_host = linux_cluster_cli_tester['cli_host']
    nodes = linux_cluster_cli_tester['nodes']
    paths = linux_cluster_cli_tester['paths']

    # stop manager services so the logs won't change during the test
    configs = ['db_config', 'rabbit_config', 'manager_config']
    for node in nodes:
        for config in configs:
            node.run_command('cfy_manager stop -c /etc/cloudify/'
                             '{}.yaml'.format(config))

    logs_dump_filepaths = json.loads(cli_host.run_command(
        '{cfy} logs download --all-nodes --json'.format(cfy=paths['cfy'])
    ).stdout.strip())['archive paths']

    # assert all logs are downloaded
    assert len(logs_dump_filepaths['manager']) == 3
    assert len(logs_dump_filepaths['db']) == 3
    assert len(logs_dump_filepaths['broker']) == 3

    for node in nodes:
        log_hashes = [f.split()[0] for f in node.run_command(
            'find /var/log/cloudify -type f -exec md5sum {} + | sort',
            use_sudo=True
        ).stdout.splitlines()]
        node_dump_filepaths = \
            [logs_dump_filepaths['manager'][node.private_ip_address]] + \
            [logs_dump_filepaths['db'][node.private_ip_address]] + \
            [logs_dump_filepaths['broker'][node.private_ip_address]]
        for dump_filepath in node_dump_filepaths:
            local_dump_path = Path(tempfile.mkdtemp())
            local_dump_filepath = local_dump_path / 'logs.tar'
            cli_host.get_remote_file(dump_filepath, local_dump_filepath)
            with tarfile.open(local_dump_filepath) as tar:
                tar.extractall(local_dump_path)
            files = list((local_dump_path / 'cloudify').rglob('*.*'))
            assert local_dump_path / 'cloudify/journalctl.log' in files
            log_hashes_local = sorted(
                [hashlib.md5(open(f, 'rb').read()).hexdigest() for f in
                 files if 'journalctl' not in f.name])
            assert set(log_hashes) == set(log_hashes_local)

    logger.info('Testing `cfy logs backup`')
    cli_host.run_command('{cfy} logs backup --verbose'.format(
        cfy=paths['cfy']))
    output = nodes[0].run_command('ls /var/log').stdout
    assert 'cloudify-manager-logs_' in output

    logger.info('Testing `cfy logs purge`')
    for node in nodes:
        for config in configs:
            node.run_command('cfy_manager stop -c /etc/cloudify/'
                             '{}.yaml'.format(config))
    cli_host.run_command('{cfy} logs purge --force'.format(cfy=paths['cfy']))
    # Verify that each file under /var/log/cloudify is size zero
    nodes[0].run_command(
        'find /var/log/cloudify -type f -exec test -s {} \\; '
        '-print -exec false {} +'
    )


def _three_node_cluster_with_extra_node(
        ssh_key, module_tmpdir, test_config, logger, request, image):
    return next(_get_hosts(ssh_key, module_tmpdir, test_config, logger,
                           request, pre_cluster_rabbit=True,
                           three_nodes_cluster=True, extra_node=image))


@pytest.fixture(
    scope='module',
    params=get_linux_image_settings())
def linux_cluster_cli_tester(request, ssh_key, module_tmpdir, test_config,
                             logger):
    cli_os = request.param[0]
    n1, n2, n3, cli_host = _three_node_cluster_with_extra_node(
        ssh_key, module_tmpdir, test_config, logger, request, cli_os)
    cluster_nodes = [n1, n2, n3]

    try:
        url_key = request.param[1]
        pkg_type = request.param[2]
        _install_cli_client(cli_host, logger, url_key, ssh_key,
                            pkg_type, test_config)

        logger.info('Copying agent ssh key and CA cert to CLI host')
        remote_ssh_key_path = '/tmp/cli_test_ssh_key.pem'
        cli_host.put_remote_file(
            remote_path=remote_ssh_key_path,
            local_path=ssh_key.private_key_path,
        )
        remote_ca_cert_path = '/tmp/cli_test_ca.cert'
        cli_host.put_remote_file(
            remote_path=remote_ca_cert_path,
            local_path='{}/ca.cert'.format(ssh_key.tmpdir),
        )

        logger.info('Using manager')
        cli_host.run_command(
            'cfy profiles use {ip} -u admin -p admin -t '
            'default_tenant --ssh-user {ssh_user} --ssh-key {ssh_key} '
            '-c {rest_cert}'.format(
                ip=cluster_nodes[0].ip_address,
                ssh_user=cluster_nodes[0].username,
                ssh_key=remote_ssh_key_path,
                rest_cert=remote_ca_cert_path,
            )
        )
        yield {
            'cli_host': cli_host,
            'nodes': cluster_nodes,
            'paths': {
                'ssh_key': remote_ssh_key_path,
                'ca_cert': remote_ca_cert_path,
                # Expected to be in path on linux systems
                'cfy': 'cfy',
            },
        }
    except Exception:
        raise


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

        _install_cli_client(cli_host, logger, url_key, ssh_key,
                            pkg_type, test_config)

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


def _install_cli_client(cli_host, logger, url_key, ssh_key,
                        pkg_type, test_config):
    logger.info('Downloading CLI package')
    cli_package_url = get_cli_package_url(url_key, test_config)
    logger.info('Using CLI package: {url}'.format(
        url=cli_package_url,
    ))
    cli_host.run_command('curl -Lo cloudify-cli.{pkg_type} {url}'.format(
        url=cli_package_url, pkg_type=pkg_type,
    ))

    logger.info('Installing CLI package')
    install_cmd = {
        'rpm': 'yum install -y',
        'deb': 'dpkg -i',
    }[pkg_type]
    cli_host.run_command(
        '{install_cmd} cloudify-cli.{pkg_type}'.format(
            install_cmd=install_cmd,
            pkg_type=pkg_type,
        ),
        use_sudo=True,
    )
