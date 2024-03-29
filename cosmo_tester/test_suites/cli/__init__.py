import json
import time
from os.path import join

import hashlib
import retrying

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import get_cli_package_url


LINUX_OSES = [
    'centos_7',
    'rhel_7',
]

WINDOWS_OSES = [
    'windows_2012',
]

LOG_BUNDLES_PATH = "/opt/manager/resources/log_bundles/"


def _prepare(cli_host, example, paths, logger, include_secret=True):
    use_ssl = False
    if example.manager.api_ca_path:
        cli_host.put_remote_file(paths['cert'], example.manager.api_ca_path)
        use_ssl = True

    logger.info('Using manager')
    cli_host.run_command(
        '{cfy} profiles use {ip} -u admin -p {pw} -t {tenant}{ssl}'.format(
            cfy=paths['cfy'],
            ip=example.manager.private_ip_address,
            pw=example.manager.mgr_password,
            tenant=example.tenant,
            ssl=' -ssl -c {}'.format(paths['cert']) if use_ssl else '',
        ),
        powershell=True,
    )

    if include_secret:
        logger.info('Creating secret')
        cli_host.run_command(
            '{cfy} secrets create --secret-file {ssh_key} agent_key'.format(
                **paths
            ),
            powershell=True,
        )


def _test_upload_and_install(run, example, paths, logger):
    logger.info('Uploading blueprint')
    run('{cfy} blueprints upload -b {bp_id} {blueprint}'.format(
        bp_id=example.blueprint_id, **paths), powershell=True)

    logger.info('Creating deployment')
    run('{cfy} deployments create -b {bp_id} -i {inputs} {dep_id} '
        .format(bp_id=example.blueprint_id, dep_id=example.deployment_id,
                **paths),
        powershell=True)

    logger.info('Executing install workflow')
    run('{cfy} executions start install -d {dep_id}'.format(
        dep_id=example.deployment_id, **paths),
        powershell=True)

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
        ),
        powershell=True,
    )

    example.check_files()


@retrying.retry(stop_max_attempt_number=15, wait_fixed=300)
def _wait_for_log_bundle_creation(run, paths, bundle_id):
    bundles = [b for b in json.loads(run(
        '{cfy} log-bundles list --json'.format(cfy=paths['cfy']),
        powershell=True
    ).stdout.strip()) if b['status'] == 'created' and b['id'] == bundle_id]
    assert len(bundles) == 1


def _test_cfy_log_bundles(
        run, cli_host, cli_os, example, paths, tmpdir, logger):
    cli_tmpdir = 'C:\\Windows\\Temp' if cli_os in WINDOWS_OSES else '/tmp'
    bundle_id = 'log_bundle_{}'.format(cli_os)

    run('{cfy} log-bundles create {bundle_id}'.format(
        cfy=paths['cfy'], bundle_id=bundle_id), powershell=True)
    _wait_for_log_bundle_creation(run, paths, bundle_id)
    run('{cfy} log-bundles download {bundle_id} -o {cli_tmpdir}'.format(
        cfy=paths['cfy'], bundle_id=bundle_id, cli_tmpdir=cli_tmpdir),
        powershell=True)

    mgr_logs_bundle_filepath = LOG_BUNDLES_PATH + bundle_id + '.zip'
    cli_logs_bundle_filepath = join(cli_tmpdir, bundle_id + '.zip')
    local_logs_bundle_filepath = str(tmpdir / bundle_id + '.zip')
    mgr_log_bundle_hash = example.manager.run_command('sudo md5sum {}'.format(
        mgr_logs_bundle_filepath)).stdout.strip().split()[0]

    if cli_os in WINDOWS_OSES:
        local_log_bundle_hash = cli_host.run_command(
            'Get-FileHash {} -Algorithm MD5 | Select-Object Hash'.format(
                cli_logs_bundle_filepath), powershell=True
        ).std_out.decode('utf-8').strip().split('\n')[-1]
    else:
        cli_host.get_remote_file(cli_logs_bundle_filepath,
                                 local_logs_bundle_filepath)
        logger.info('Downloaded log bundle to %s', local_logs_bundle_filepath)
        local_log_bundle_hash = hashlib.md5(
            open(local_logs_bundle_filepath, 'rb').read()).hexdigest()

    logger.info('Log bundle hashes: %s %s',
                mgr_log_bundle_hash, local_log_bundle_hash)
    assert mgr_log_bundle_hash.lower() == local_log_bundle_hash.lower()


def _test_teardown(run, example, paths, logger):
    logger.info('Starting uninstall workflow')
    run('{cfy} executions start uninstall -d {dep_id}'.format(
        dep_id=example.deployment_id, **paths),
        powershell=True)

    example.check_all_test_files_deleted()

    logger.info('Deleting deployment')
    run('{cfy} deployments delete {dep_id}'.format(
        dep_id=example.deployment_id, **paths),
        powershell=True)
    # With a sleep because this returns before the DB is updated
    time.sleep(4)

    logger.info('Checking deployment has been deleted.')
    deployments = json.loads(
        run('{cfy} deployments list --json'.format(**paths),
            powershell=True).stdout
    )
    assert len(deployments) == 0

    logger.info('Deleting secret')
    run('{cfy} secrets delete agent_key'.format(**paths), powershell=True)

    logger.info('Checking secret has been deleted.')
    secrets = json.loads(
        run('{cfy} secrets list --json'.format(**paths),
            powershell=True).stdout
    )
    assert len(secrets) == 0

    logger.info('Deleting blueprint')
    run('{cfy} blueprints delete {bp_id}'.format(
        bp_id=example.blueprint_id, **paths),
        powershell=True)
    # With a sleep because this returns before the DB is updated
    time.sleep(4)

    logger.info('Checking blueprint has been deleted.')
    blueprints = json.loads(
        run('{cfy} blueprints list --json'.format(**paths),
            powershell=True).stdout
    )
    assert len(blueprints) == 0


def _cleanup_profile(run, example, paths, logger, include_secret=True):
    if include_secret:
        logger.info('Creating secret')
        run('{cfy} secrets delete agent_key'.format(
                **paths),
            powershell=True)

    logger.info('Removing CLI profile')
    run('{cfy} profiles delete {ip}'.format(
        cfy=paths['cfy'],
        ip=example.manager.private_ip_address),
        powershell=True)


def _install_linux_cli(cli_host, logger, test_config):
    logger.info('Downloading CLI package')
    cli_package_url = get_cli_package_url('rhel', test_config, cli_host)
    logger.info('Using CLI package: {url}'.format(
        url=cli_package_url,
    ))
    cli_host.run_command('curl -Lo cloudify-cli.rpm {url}'.format(
        url=cli_package_url,
    ))

    logger.info('Installing CLI package')
    install_cmd = 'yum install -y'
    cli_host.run_command(
        '{install_cmd} cloudify-cli.rpm'.format(
            install_cmd=install_cmd,
        ),
        use_sudo=True,
    )


def _prepare_linux_cli_test_components(cli_host, manager_host, cli_os,
                                       ssh_key, logger, test_config):
    cli_host.wait_for_ssh()

    _install_linux_cli(cli_host, logger, test_config)

    example = get_example_deployment(
        manager_host, ssh_key, logger, 'cli_test_{}'.format(cli_os),
        test_config)
    example.inputs['path'] = '/tmp/{}'.format(cli_os)

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

    return {
        'cli_host': cli_host,
        'example': example,
        'windows': False,
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


def _prepare_windows_cli_test_components(cli_host, manager_host, cli_os,
                                         ssh_key, logger, test_config):
    url_key = 'windows'

    cli_host.wait_for_winrm()

    work_dir = 'C:\\Users\\{0}'.format(cli_host.username)
    cli_installer_exe_name = 'cloudify-cli.exe'
    cli_installer_exe_path = '{0}\\{1}'.format(work_dir,
                                               cli_installer_exe_name)

    logger.info('Downloading CLI package')
    cli_package_url = get_cli_package_url(url_key, test_config, cli_host)
    cli_package_version = cli_package_url.split('.exe')[-2].split('_')[-1]
    logger.info('Using CLI package: {url}'.format(
        url=cli_package_url,
    ))
    cli_host.run_command(
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
    cli_host.run_command(
        '''
cd {0}
& .\\{1} /SILENT /VERYSILENT /SUPPRESSMSGBOXES'''
        .format(work_dir, cli_installer_exe_name),
        powershell=True,
    )

    example = get_example_deployment(
        manager_host, ssh_key, logger, url_key, test_config,
        vm=cli_host)
    example.use_windows(cli_host.username, cli_host.password)

    logger.info('Copying blueprint to CLI host')
    remote_blueprint_path = work_dir + '\\Documents\\blueprint.yaml'
    with open(example.blueprint_file) as blueprint_handle:
        blueprint = blueprint_handle.read()
    cli_host.put_remote_file_content(remote_blueprint_path, blueprint)

    logger.info('Copying inputs to CLI host')
    remote_inputs_path = work_dir + '\\Documents\\inputs.yaml'
    cli_host.put_remote_file_content(remote_inputs_path,
                                     json.dumps(example.inputs))

    logger.info('Copying agent ssh key to CLI host for secret')
    remote_ssh_key_path = work_dir + '\\Documents\\ssh_key.pem'
    with open(ssh_key.private_key_path) as ssh_key_handle:
        ssh_key_data = ssh_key_handle.read()
    cli_host.put_remote_file_content(remote_ssh_key_path, ssh_key_data)

    return {
        'cli_host': cli_host,
        'example': example,
        'windows': True,
        'paths': {
            'blueprint': remote_blueprint_path,
            'inputs': remote_inputs_path,
            'ssh_key': remote_ssh_key_path,
            'cfy': '& "C:\\Program Files\\Cloudify {} CLI\\Scripts\\'
                   'cfy.exe"'.format(cli_package_version),
            'cert': '"C:\\Users\\{username}\\manager.crt"'.format(
                username=cli_host.username),
        },
    }
