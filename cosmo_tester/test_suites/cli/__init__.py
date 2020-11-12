import json
import time
import hashlib
import tarfile
import tempfile
from pathlib import Path
from invoke import UnexpectedExit


def get_image_and_username(os, test_config):
    image = test_config.platform['{}_image'.format(os)]
    username = test_config['test_os_usernames'][os]
    return image, username


def _prepare(run, example, paths, logger):
    logger.info('Using manager')
    run(
        '{cfy} profiles use {ip} -u admin -p admin -t {tenant}'.format(
            cfy=paths['cfy'],
            ip=example.manager.private_ip_address,
            tenant=example.tenant,
        )
    )

    logger.info('Creating secret')
    run('{cfy} secrets create --secret-file {ssh_key} agent_key'
        .format(**paths))


def _test_upload_and_install(run, example, paths, logger):
    logger.info('Uploading blueprint')
    run('{cfy} blueprints upload -b {bp_id} {blueprint}'.format(
        bp_id=example.blueprint_id, **paths))

    logger.info('Creating deployment')
    run('{cfy} deployments create -b {bp_id} -i {inputs} {dep_id} '
        .format(bp_id=example.blueprint_id, dep_id=example.deployment_id,
                **paths))

    logger.info('Executing install workflow')
    run('{cfy} executions start install -d {dep_id}'.format(
        dep_id=example.deployment_id, **paths))

    example.check_files()


def _test_cfy_install(run, example, paths, logger):
    logger.info('Running cfy install for blueprint')
    run(
        '{cfy} install --blueprint-id {blueprint} '
        '--deployment-id {deployment} --inputs {inputs} '
        '{blueprint_path}'.format(
            cfy=paths['cfy'],
            blueprint=example.blueprint_id,
            deployment=example.deployment_id,
            inputs=paths['inputs'],
            blueprint_path=paths['blueprint'],
        )
    )

    example.check_files()


def _set_ssh_in_profile(run, example, paths):
    run(
        '{cfy} profiles set --ssh-user {ssh_user} --ssh-key {ssh_key}'.format(
            cfy=paths['cfy'],
            ssh_user=example.manager.username,
            ssh_key=paths['ssh_key'],
        )
    )


def _test_cfy_logs(run, cli_host, example, paths, logger):
    _set_ssh_in_profile(run, example, paths)

    # stop manager services so the logs won't change during the test
    example.manager.run_command('cfy_manager stop')

    logs_dump_filepath = [v for v in json.loads(run(
        '{cfy} logs download --json'.format(cfy=paths['cfy'])
    ).stdout.strip())['archive paths']['manager'].values()][0]

    log_hashes = [f.split()[0] for f in example.manager.run_command(
        'find /var/log/cloudify -type f -exec md5sum {} \; | sort',  # NOQA
        use_sudo=True
    ).stdout.splitlines() if 'access' not in f]

    local_logs_dump_path = Path(tempfile.mkdtemp())
    local_logs_dump_filepath = local_logs_dump_path / 'logs.tar'
    cli_host.get_remote_file(logs_dump_filepath, local_logs_dump_filepath)
    with tarfile.open(local_logs_dump_filepath) as tar:
        tar.extractall(local_logs_dump_path)

    files = list((local_logs_dump_path / 'cloudify').rglob('*.*'))
    assert local_logs_dump_path / 'cloudify/journalctl.log' in files
    assert local_logs_dump_path / 'cloudify/nginx/cloudify.access.log' in files
    log_hashes_local = sorted(
        [hashlib.md5(open(f, 'rb').read()).hexdigest() for f in files if
         not ('journalctl' in f.name or 'access' in f.name)])
    assert set(log_hashes) == set(log_hashes_local)

    logger.info('Testing `cfy logs backup`')
    run('{cfy} logs backup --verbose'.format(cfy=paths['cfy']))
    output = example.manager.run_command('ls /var/log').stdout
    assert 'cloudify-manager-logs_' in output

    logger.info('Testing `cfy logs purge`')
    example.manager.run_command('cfy_manager stop')
    run('{cfy} logs purge --force'.format(cfy=paths['cfy']))
    # Verify that each file under /var/log/cloudify is size zero
    example.manager.run_command(
        'find /var/log/cloudify -type f -exec test -s {} \; '  # NOQA
        '-print -exec false {} +'
    )


def _test_tmux_session(run, run_manager, example, paths, logger):
    # this will go away after installing tmux in build-iamges pipeline
    run_manager('sudo yum install tmux -y')

    _set_ssh_in_profile(run, example, paths)

    logger.info('Disabling tmux...')
    tmux_path = run_manager('which tmux').stdout.strip()
    run_manager('mv {tmux} {tmux}.old'.format(tmux=tmux_path), use_sudo=True)

    logger.info('Test listing sessions failing when no tmux on manager')
    try:
        run('{cfy} ssh --list-sessions'.format(cfy=paths['cfy']))
    except UnexpectedExit as e:
        assert 'tmux not found on the manager' in e.result.stdout
    except AssertionError as e:     # For Windows CLI
        tb = e.__traceback__.tb_next.tb_frame.f_locals['result'].std_out
        assert b'tmux not found on the manager' in tb

    logger.info('Enabling tmux...')
    run_manager('mv {tmux}.old {tmux}'.format(tmux=tmux_path), use_sudo=True)

    logger.info('Test listing sessions when none are available..')
    output = run('{cfy} ssh --list-sessions'.format(cfy=paths['cfy'])).stdout
    assert 'No sessions are available' in str(output)

    logger.info('Test running ssh command...')
    if 'C:\\' in paths['cfy']:
        output = run('{cfy} ssh --command pwd'.format(cfy=paths['cfy']))
        output = output.stdout.decode().strip()
        assert '/home/{}'.format(example.manager.username) == output
    else:
        content = 'yay'
        remote_path = '/tmp/ssh_test_output_file'
        command = 'echo {0} > {1}'.format(content, remote_path)
        run('{cfy} ssh --command \'{command}\''.format(cfy=paths['cfy'],
                                                       command=command))
        output = run_manager('cat {}'.format(remote_path)).stdout.strip()
        assert content == output


def _test_teardown(run, example, paths, logger):
    logger.info('Starting uninstall workflow')
    run('{cfy} executions start uninstall -d {dep_id}'.format(
        dep_id=example.deployment_id, **paths))

    example.check_all_test_files_deleted()

    logger.info('Deleting deployment')
    run('{cfy} deployments delete {dep_id}'.format(
        dep_id=example.deployment_id, **paths))
    # With a sleep because this returns before the DB is updated
    time.sleep(4)

    logger.info('Checking deployment has been deleted.')
    deployments = json.loads(
        run('{cfy} deployments list --json'.format(**paths)).stdout
    )
    assert len(deployments) == 0

    logger.info('Deleting secret')
    run('{cfy} secrets delete agent_key'.format(**paths))

    logger.info('Checking secret has been deleted.')
    secrets = json.loads(
        run('{cfy} secrets list --json'.format(**paths)).stdout
    )
    assert len(secrets) == 0

    logger.info('Deleting blueprint')
    run('{cfy} blueprints delete {bp_id}'.format(
        bp_id=example.blueprint_id, **paths))
    # With a sleep because this returns before the DB is updated
    time.sleep(4)

    logger.info('Checking blueprint has been deleted.')
    blueprints = json.loads(
        run('{cfy} blueprints list --json'.format(**paths)).stdout
    )
    assert len(blueprints) == 0
