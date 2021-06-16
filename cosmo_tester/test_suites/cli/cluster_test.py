import json
import pytest
import hashlib
import tarfile

from cosmo_tester.test_suites.cli import (
    _install_linux_cli,
    _prepare,
    _test_cfy_logs,
    get_linux_image_settings,
)


@pytest.mark.parametrize('three_node_cluster_with_extra_node',
                         [p[0] for p in get_linux_image_settings()],
                         indirect=['three_node_cluster_with_extra_node'])
def test_cfy_logs_linux_cluster(request, ssh_key, test_config, logger,
                                three_node_cluster_with_extra_node, tmpdir):
    linux_cluster_cli_tester = _linux_cluster_cli_tester(
        request, ssh_key, test_config, logger,
        three_node_cluster_with_extra_node)

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
        logger.info('Checking log hashes for `node %s`', node.hostname)
        log_hashes = [f.split()[0] for f in node.run_command(
            'find /var/log/cloudify -type f -not -name \'supervisord.log\''
            ' -exec md5sum {} + | sort',
            use_sudo=True
        ).stdout.splitlines()]
        logger.info('Calculated log hashes for %s are %s',
                    node.hostname, log_hashes)
        node_dump_filepaths = \
            [logs_dump_filepaths['manager'][node.private_ip_address]] + \
            [logs_dump_filepaths['db'][node.private_ip_address]] + \
            [logs_dump_filepaths['broker'][node.private_ip_address]]
        for i, dump_filepath in enumerate(node_dump_filepaths):
            tar_name = 'logs_{0}_{1}'.format(node.hostname, i)
            logger.info('Start extracting log hashes locally for %s', tar_name)
            local_dump_filepath = str(tmpdir / '{}.tar'.format(tar_name))
            cli_host.get_remote_file(dump_filepath, local_dump_filepath)
            with tarfile.open(local_dump_filepath) as tar:
                tar.extractall(str(tmpdir / tar_name))
            files = list((tmpdir / tar_name / 'cloudify').visit('*.*'))
            logger.info('Checking both `journalctl.log` and '
                        '`supervisord.log` are exist inside %s', tar_name)
            assert str(tmpdir / tar_name / 'cloudify/journalctl.log') in files
            assert str(tmpdir / tar_name / 'cloudify/supervisord.log') in files
            log_hashes_local = sorted(
                [hashlib.md5(open(f.strpath, 'rb').read()).hexdigest() for f
                 in files if 'journalctl' not in f.basename
                 and 'supervisord' not in f.basename]
            )
            logger.info('Calculated log hashes locally for %s are %s',
                        node.hostname, log_hashes_local)
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
    logger.info('Verifying each file under /var/log/cloudify is size zero')
    nodes[0].run_command(
        'find /var/log/cloudify -type f -not -name \'supervisord.log\''
        ' -exec test -s {} \\; -print -exec false {} +',
        use_sudo=True,
    )


def _linux_cluster_cli_tester(request, ssh_key, test_config, logger, cluster):
    cluster_nodes = cluster[:3]
    cli_host = cluster[3]

    try:
        _install_linux_cli(cli_host, logger, test_config)

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
        return {
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
