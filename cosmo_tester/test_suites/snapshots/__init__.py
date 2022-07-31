import json
import os
from time import sleep

import retrying

from cloudify.snapshots import STATES
from cloudify_rest_client.exceptions import UserUnauthorizedError

from cosmo_tester.framework.constants import SUPPORTED_RELEASES
from cosmo_tester.framework.util import (
    assert_snapshot_created,
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
    '/opt/manager/resources/deployments/{tenant}'
)
DEPLOYMENT_ENVIRONMENT_PATH = TENANT_DEPLOYMENTS_PATH + '/{name}'


def get_multi_tenant_versions_list():
    return SUPPORTED_RELEASES


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


def confirm_manager_empty(manager, logger):
    logger.info('Confirming only default tenant exists on manager')
    tenants = [t['name'] for t in manager.client.tenants.list()]
    assert tenants == ['default_tenant']

    clean = {
        'default_tenant': {
            'plugins': [],
            'blueprints': [],
            'deployments': [],
            'secrets': [],
        }
    }
    logger.info('Confirming default tenant has no resources')
    assert get_manager_state(manager, ['default_tenant'], logger) == clean


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


def create_copy_and_restore_snapshot(old_manager, new_manager,
                                     snapshot_id, local_snapshot_path,
                                     logger,
                                     wait_for_post_restore_commands=True,
                                     cert_path=None):
    create_snapshot(old_manager, SNAPSHOT_ID, logger)
    download_snapshot(old_manager, local_snapshot_path, SNAPSHOT_ID, logger)
    upload_snapshot(new_manager, local_snapshot_path, SNAPSHOT_ID, logger)
    restore_snapshot(
        new_manager, SNAPSHOT_ID, logger,
        wait_for_post_restore_commands=wait_for_post_restore_commands,
        cert_path=cert_path, admin_password=old_manager.mgr_password)
    wait_for_restore(new_manager, logger)


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
    manager.client = manager.get_rest_client(password=new_password)


def _retry_if_file_not_found(exception):
    return 'no such file or directory' in str(exception).lower()


# Retry if the snapshot was not found to work around syncthing delays
@retrying.retry(
    retry_on_exception=_retry_if_file_not_found,
    stop_max_attempt_number=10,
    wait_fixed=1500,
)
def restore_snapshot(manager, snapshot_id, logger, admin_password,
                     restore_certificates=False, force=False,
                     wait_for_post_restore_commands=True,
                     wait_timeout=20, cert_path=None, blocking=True):
    list_snapshots(manager, logger)

    logger.info('Restoring snapshot on latest manager..')
    restore_execution = manager.client.snapshots.restore(
        snapshot_id,
        restore_certificates=restore_certificates,
        force=force
    )

    if blocking:
        logger.info('Waiting to give time for snapshot to restore')
        # Because the DB migrations are really temperamental since 5.0.5, so
        # let's try to give less activity
        sleep(60)
        completed = False
        password_reset = False
        try:
            # Retry while the password is still being reset
            attempt = 0
            while attempt < 60:
                try:
                    wait_for_execution(
                        manager.client,
                        restore_execution,
                        logger,
                        allow_client_error=True)
                    completed = True
                    break
                except UserUnauthorizedError:
                    # We may see this exception even without the password
                    # being changed due to rest-security.conf updates
                    if not password_reset:
                        change_rest_client_password(manager, admin_password)
                        update_credentials(manager, logger, admin_password)
                        password_reset = True
                    sleep(2)
                    attempt += 1
        except ExecutionFailed:
            logger.error('Snapshot execution failed.')
            list_executions(manager, logger)
            raise

        if not completed:
            raise RuntimeError('Snapshot restore did not succeed in time.')

        # wait a while to allow the restore-snapshot post-workflow commands to
        # run
        if wait_for_post_restore_commands:
            sleep(wait_timeout)


def prepare_credentials_tests(manager, logger):
    logger.info('Creating test user')
    create_user('testuser', 'testpass', manager)


def update_credentials(manager, logger, admin_password):
    logger.info('Changing to modified admin credentials')
    change_rest_client_password(manager, admin_password)
    logger.info('Updating manager CLI credentials')
    # Skip validating the credentials because the manager will be mid restore
    # when we are setting this
    manager.run_command(
        'cfy profiles set --manager-password {} '
        '--skip-credentials-validation'.format(admin_password))


def check_credentials(manager, logger):
    logger.info('Checking test user still works')
    test_user('testuser', 'testpass', manager, logger)


def create_user(username, password, manager):
    manager.client.users.create(username, password, 'sys_admin')


def test_user(username, password, manager, logger):
    logger.info('Checking {user} can log in.'.format(user=username))
    client = manager.get_rest_client(username=username, password=password)
    client.manager.get_status()


def check_deployments(manager, expected_state, logger):
    """Make sure the deployments were fully recreated"""
    for tenant, details in expected_state.items():
        deployments = details['deployments']

        _log('Checking deployments', logger, tenant)
        # Now make sure the envs were recreated
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
            manager.run_command(
                'ls -la {path}'.format(
                    path=TENANT_DEPLOYMENTS_PATH.format(
                        tenant=tenant,
                    ),
                ),
                use_sudo=True,
            )
            _log(
                'Checking deployment path for {name}'.format(
                    name=deployment,
                ),
                logger,
                tenant,
            )
            manager.run_command('test -d {path}'.format(path=path),
                                use_sudo=True)
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
            logs = manager.run_command(
                'journalctl -u {0} -n 20 --no-pager'.format(instance['Id']),
                use_sudo=True).stdout
            logger.info('Journald logs of the failing service:')
            logger.info(logs)
            raise Exception('Service {0} is in status {1}'.
                            format(instance, instance['state']))


def get_manager_state(manager, tenants, logger):
    tenant_state = {}
    for tenant in tenants:
        tenant_state[tenant] = {}

        logger.info('Getting plugin details for tenant %s', tenant)
        with set_client_tenant(manager.client, tenant):
            tenant_state[tenant]['plugins'] = sorted([
                (
                    item['package_name'],
                    item['package_version'],
                    item['distribution'],
                )
                for item in manager.client.plugins.list()
            ])

        logger.info('Getting blueprints for tenant %s', tenant)
        with set_client_tenant(manager.client, tenant):
            tenant_state[tenant]['blueprints'] = sorted([
                item['id'] for item in manager.client.blueprints.list()
            ])

        logger.info('Getting deployments for tenant %s', tenant)
        with set_client_tenant(manager.client, tenant):
            tenant_state[tenant]['deployments'] = sorted([
                item['id'] for item in manager.client.deployments.list()
            ])

        logger.info('Getting secrets for tenant %s', tenant)
        with set_client_tenant(manager.client, tenant):
            tenant_state[tenant]['secrets'] = sorted([
                item['key'] for item in manager.client.secrets.list()
            ])
    return tenant_state


def _log(message, logger, tenant=None):
    if tenant:
        message += ' for {tenant}'.format(tenant=tenant)
    logger.info(message)


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
