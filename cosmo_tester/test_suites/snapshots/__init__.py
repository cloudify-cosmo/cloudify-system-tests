import json
import os
from time import sleep

import retrying

from cloudify.snapshots import STATES
from cloudify_rest_client.exceptions import UserUnauthorizedError

from cosmo_tester.framework.util import (
    assert_snapshot_created,
    create_rest_client,
    ExecutionFailed,
    list_executions,
    list_snapshots,
    set_client_tenant,
    wait_for_execution,
)


SNAPSHOT_ID = 'testsnapshot'
# This is used purely for testing that plugin restores have occurred.
# Any plugin should work.
BASE_PLUGIN_PATH = '/opt/mgmtworker/env/plugins/{tenant}/'
INSTALLED_PLUGIN_PATH = BASE_PLUGIN_PATH + '{name}-{version}'
FROM_SOURCE_PLUGIN_PATH = BASE_PLUGIN_PATH + '{deployment}-{plugin}'
TENANT_DEPLOYMENTS_PATH = (
    '/opt/mgmtworker/work/deployments/{tenant}'
)
DEPLOYMENT_ENVIRONMENT_PATH = (
    '/opt/mgmtworker/work/deployments/{tenant}/{name}'
)
CHANGED_ADMIN_PASSWORD = 'changedmin'

# These manager versions support multiple tenant snapshot restores in premium
MULTI_TENANT_MANAGERS = (
    '4.3.1',
    '4.4',
    '4.5',
    '4.5.5',
    '4.6',
    '5.0.5',
    'master',
)


def get_multi_tenant_versions_list():
    return MULTI_TENANT_MANAGERS


def upgrade_agents(manager, logger, test_config):
    logger.info('Upgrading agents')
    command = 'cfy agents install'
    if test_config['premium']:
        command += ' --all-tenants'
    manager.run_command(command)


def stop_manager(manager, logger):
    logger.info('Stopping {version} manager..'.format(
        version=manager.image_type))
    manager.stop()


def check_from_source_plugin(manager, plugin, deployment_id, logger,
                             tenant='default_tenant'):
    with manager.ssh() as fabric_ssh:
        _log(
            'Checking plugin {plugin} was installed from source for '
            'deployment {deployment}'.format(
                plugin=plugin,
                deployment=deployment_id,
            ),
            logger,
            tenant,
        )
        path = FROM_SOURCE_PLUGIN_PATH.format(
            plugin=plugin,
            deployment=deployment_id,
            tenant=tenant,
        )
        fabric_ssh.sudo('test -d {path}'.format(path=path))
        logger.info('Plugin installed from source successfully.')


def confirm_manager_empty(manager):
    assert get_plugins_list(manager) == []
    assert get_deployments_list(manager) == []


def create_snapshot(manager, snapshot_id, logger):
    logger.info('Creating snapshot on manager {image_name}'
                .format(image_name=manager.image_name))
    manager.client.snapshots.create(
        snapshot_id=snapshot_id,
        include_credentials=True,
        include_logs=True,
        include_events=True
    )
    assert_snapshot_created(manager, snapshot_id)


def download_snapshot(manager, local_path, snapshot_id, logger):
    logger.info('Downloading snapshot from old manager..')
    manager.client.snapshots.list()
    manager.client.snapshots.download(snapshot_id, local_path)


def upload_snapshot(manager, local_path, snapshot_id, logger):
    logger.info('Uploading snapshot to latest manager..')
    snapshot = manager.client.snapshots.upload(local_path,
                                               snapshot_id)
    logger.info('Uploaded snapshot:%s%s',
                os.linesep,
                json.dumps(snapshot, indent=2))


def change_rest_client_password(manager, new_password):
    manager.client = create_rest_client(manager.ip_address,
                                        password=new_password)


def _retry_if_file_not_found(exception):
    return 'no such file or directory' in str(exception).lower()


# Retry if the snapshot was not found to work around syncthing delays
@retrying.retry(
    retry_on_exception=_retry_if_file_not_found,
    stop_max_attempt_number=10,
    wait_fixed=1500,
)
def restore_snapshot(manager, snapshot_id, logger,
                     restore_certificates=False, force=False,
                     wait_for_post_restore_commands=True,
                     wait_timeout=20, change_manager_password=True,
                     cert_path=None, blocking=True):
    list_snapshots(manager, logger)

    logger.info('Restoring snapshot on latest manager..')
    restore_execution = manager.client.snapshots.restore(
        snapshot_id,
        restore_certificates=restore_certificates,
        force=force
    )

    _assert_restore_status(manager)

    if blocking:
        try:
            try:
                wait_for_execution(
                    manager.client,
                    restore_execution,
                    logger)
            except UserUnauthorizedError:
                change_rest_client_password(manager, CHANGED_ADMIN_PASSWORD)
                wait_for_execution(
                    manager.client,
                    restore_execution,
                    logger)
        except ExecutionFailed:
            logger.error('Snapshot execution failed.')
            list_executions(manager, logger)
            raise

        # wait a while to allow the restore-snapshot post-workflow commands to
        # run
        if wait_for_post_restore_commands:
            sleep(wait_timeout)


def change_salt_on_new_manager(manager, logger):
    change_salt(manager, 'this_is_a_test_salt', logger)


def prepare_credentials_tests(manager, logger):
    logger.info('Creating test user')
    create_user('testuser', 'testpass', manager)
    logger.info('Updating admin password')
    change_rest_client_password(manager, CHANGED_ADMIN_PASSWORD)


def update_credentials(manager, logger):
    logger.info('Changing to modified admin credentials')
    change_rest_client_password(manager, CHANGED_ADMIN_PASSWORD)


def check_credentials(manager, logger):
    logger.info('Checking test user still works')
    test_user('testuser', 'testpass', manager, logger)


def create_user(username, password, manager):
    manager.client.users.create(username, password, 'sys_admin')


def test_user(username, password, manager, logger):
    logger.info('Checking {user} can log in.'.format(user=username))
    create_rest_client(
        manager.ip,
        username,
        password,
    ).get_status()


def get_security_conf(manager):
    with manager.ssh() as fabric_ssh:
        output = fabric_ssh.sudo('cat /opt/manager/rest-security.conf').stdout
    # No real error checking here; the old manager shouldn't be able to even
    # start the rest service if this file isn't json.
    return json.loads(output)


def change_salt(manager, new_salt, logger):
    """Change the salt on the manager so that we don't incorrectly succeed
    while testing non-admin users due to both copies of the master image
    having the same hash salt value."""
    logger.info('Preparting to update salt on {manager}'.format(
        manager=manager.ip_address,
    ))
    security_conf = get_security_conf(manager)

    original_salt = security_conf['hash_salt']
    security_conf['hash_salt'] = new_salt

    logger.info('Applying new salt...')
    with manager.ssh() as fabric_ssh:
        fabric_ssh.sudo(
            "sed -i 's:{original}:{replacement}:' "
            "/opt/manager/rest-security.conf".format(
                original=original_salt,
                replacement=new_salt,
            )
        )

        fabric_ssh.sudo('systemctl restart cloudify-restservice')

    logger.info('Fixing admin credentials...')
    fix_admin_account(manager, new_salt, logger)

    logger.info('Hash updated.')


def fix_admin_account(manager, salt, logger):
    manager.run_command('cfy_manager reset-admin-password admin')
    test_user('admin', 'admin', manager, logger)


def check_plugins(manager, old_plugins, logger, tenant='default_tenant'):
    """
        Make sure that all plugins on the manager are correctly installed.
        This checks not just for their existence in the API, but also that
        they exist in the correct place on the manager filesystem.
        This is intended for use checking a new manager has all plugins
        correctly restored by a snapshot.

        :param manager: The manager to check.
        :param old_plugins: A list of plugins on the old manager. This will be
                            checked to confirm that all of the plugins have
                            been restored on the new manager.
        :param logger: A logger to provide useful output.
        :param tenant: Set to check tenants other than the default tenant.
                       Whichever tenant name this is set to will be checked.
                       Defaults to default_tenant.
    """
    _log('Checking plugins', logger, tenant)
    plugins = get_plugins_list(manager, tenant)
    assert plugins == old_plugins

    # Now make sure they're correctly installed
    with manager.ssh() as fabric_ssh:
        for plugin_name, plugin_version, _ in plugins:
            path = INSTALLED_PLUGIN_PATH.format(
                tenant=tenant,
                name=plugin_name,
                version=plugin_version,
            )
            logger.info('Checking plugin {name} is in {path}'.format(
                name=plugin_name,
                path=path,
            ))
            fabric_ssh.sudo('test -d {path}'.format(path=path))
            logger.info('Plugin is correctly installed.')

    _log('Plugins as expected', logger, tenant)


def check_deployments(manager, old_deployments, logger,
                      tenant='default_tenant'):
    deployments = get_deployments_list(manager, tenant)
    assert sorted(deployments) == sorted(old_deployments)

    _log('Checking deployments', logger, tenant)
    # Now make sure the envs were recreated
    with manager.ssh() as fabric_ssh:
        for deployment in deployments:
            path = DEPLOYMENT_ENVIRONMENT_PATH.format(
                tenant=tenant,
                name=deployment,
            )
            logger.info(
                'Checking deployment env for {name} was recreated.'.format(
                    name=deployment,
                )
            )
            # To aid troubleshooting when the following line fails
            _log('Listing deployments path', logger, tenant)
            fabric_ssh.sudo('ls -la {path}'.format(
                path=TENANT_DEPLOYMENTS_PATH.format(
                    tenant=tenant,
                ),
            ))
            _log(
                'Checking deployment path for {name}'.format(
                    name=deployment,
                ),
                logger,
                tenant,
            )
            fabric_ssh.sudo('test -d {path}'.format(path=path))
            logger.info('Deployment environment was recreated.')
    _log('Found correct deployments', logger, tenant)


@retrying.retry(
    stop_max_attempt_number=10,
    wait_fixed=1500
)
def verify_services_status(manager, logger):
    logger.info('Verifying services status...')
    manager_status = manager.client.manager.get_status()
    if manager_status['status'] == 'OK':
        return

    for display_name, service in manager_status['services'].items():
        if service['status'] == 'Active':
            continue
        extra_info = service.get('extra_info', {})
        systemd = extra_info.get('systemd', {})
        for instance in systemd.get('instances', []):
            with manager.ssh() as fabric:
                logs = fabric.sudo('journalctl -u {0} -n 20 --no-pager'
                                   .format(instance['Id'])).stdout
            logger.info('Journald logs of the failing service:')
            logger.info(logs)
            raise Exception('Service {0} is in status {1}'.
                            format(instance, instance['state']))


def get_plugins_list(manager, tenant=None):
    with set_client_tenant(manager.client, tenant):
        return [
            (
                item['package_name'],
                item['package_version'],
                item['distribution'],
            )
            for item in manager.client.plugins.list()
        ]


def get_deployments_list(manager, tenant=None):
    with set_client_tenant(manager.client, tenant):
        return [
            item['id'] for item in manager.client.deployments.list()
        ]


def get_secrets_list(manager, tenant=None):
    with set_client_tenant(manager.client, tenant):
        return [
            item['key'] for item in manager.client.secrets.list()
        ]


def _log(message, logger, tenant=None):
    if tenant:
        message += ' for {tenant}'.format(tenant=tenant)
    logger.info(message)


@retrying.retry(
    stop_max_attempt_number=10,
    wait_fixed=1000
)
def _assert_restore_status(manager):
    """
    Assert the snapshot-status REST endpoint is working properly
    """
    restore_status = manager.client.snapshots.get_status()
    assert restore_status['status'] == STATES.RUNNING


# There is a short delay after the snapshot finishes restoring before the
# post-restore commands finish running, so we'll give it time
# create-admin-token is rarely taking 1.5+ minutes to execute, so three
# minutes are allowed for it
@retrying.retry(stop_max_attempt_number=36, wait_fixed=5000)
def wait_for_restore(manager, logger):
    restore_status = manager.client.snapshots.get_status()
    logger.info('Current snapshot status: %s, waiting for %s',
                restore_status, STATES.NOT_RUNNING)
    assert STATES.NOT_RUNNING == restore_status['status']
