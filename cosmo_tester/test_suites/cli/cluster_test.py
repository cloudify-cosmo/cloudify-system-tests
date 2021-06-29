import json
import tarfile

from cosmo_tester.test_suites.cli import (
    _get_local_log_hashes,
    _get_manager_log_hashes,
    LINUX_OSES,
    _prepare,
    _test_logs_context,
)


def test_cfy_logs_linux_cluster(request, ssh_key, test_config, logger,
                                cluster_cli_tester, tmpdir):
    # We can't currently cleanly test logs on windows (need CLI unzip on 2012,
    # but it's only in powershell from 2016(?)).
    for os in LINUX_OSES:
        cli_host = cluster_cli_tester[os]['cli_host']
        example = cluster_cli_tester[os]['example']
        paths = cluster_cli_tester[os]['paths']
        tmpdir = cluster_cli_tester['tmpdir']
        managers = cluster_cli_tester['managers']

        _prepare(cli_host, example, paths, logger, include_secret=False)

        with _test_logs_context(cli_host.run_command, example, paths,
                                cluster_cli_tester['managers']):
            log_dump_paths = json.loads(cli_host.run_command(
                '{cfy} logs download --all-nodes --json'.format(
                    cfy=paths['cfy'])
            ).stdout.strip())['archive paths']

            # assert all logs are downloaded
            assert len(log_dump_paths['manager']) == 3
            assert len(log_dump_paths['db']) == 3
            assert len(log_dump_paths['broker']) == 3

            for manager in managers:
                log_hashes = _get_manager_log_hashes(manager, logger)
                manager_ip = manager.private_ip_address

                mgr_dump_paths = \
                    [log_dump_paths['manager'][manager_ip]] + \
                    [log_dump_paths['db'][manager_ip]] + \
                    [log_dump_paths['broker'][manager_ip]]
                for i, dump_filepath in enumerate(mgr_dump_paths):
                    tar_name = 'logs_{}_{}_{}'.format(manager.hostname, i, os)
                    logger.info('Start extracting log hashes locally for %s',
                                tar_name)
                    local_dump_filepath = str(tmpdir / '{}.tar'.format(
                        tar_name))
                    cli_host.get_remote_file(dump_filepath,
                                             local_dump_filepath)
                    with tarfile.open(local_dump_filepath) as tar:
                        tar.extractall(str(tmpdir / os / tar_name))

                    local_base = (tmpdir / os / tar_name / 'cloudify')
                    log_hashes_local = _get_local_log_hashes(local_base,
                                                             logger)

                    assert log_hashes == log_hashes_local

            logger.info('Testing `cfy logs backup`')
            cli_host.run_command('{cfy} logs backup --verbose'.format(
                cfy=paths['cfy']))
            output = managers[0].run_command('ls /var/log').stdout
            assert 'cloudify-manager-logs_' in output

            logger.info('Testing `cfy logs purge`')
            cli_host.run_command('{cfy} logs purge --force'.format(
                                  cfy=paths['cfy']))
            # Verify that each file under /var/log/cloudify is size zero
            logger.info('Verifying each file under /var/log/cloudify '
                        'is size zero')
            managers[0].run_command(
                'find /var/log/cloudify -type f -not -name \'supervisord.log\''
                ' -exec test -s {} \\; -print -exec false {} +',
                use_sudo=True,
            )
