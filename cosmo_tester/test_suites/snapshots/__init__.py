#######
# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import base64
import hashlib
import hmac
import json
import os
from time import sleep

import retrying
from passlib.context import CryptContext

from cloudify.snapshots import STATES
from cosmo_tester.framework.test_hosts import (
    TestHosts,
    get_image,
)
from cosmo_tester.framework.util import (
    assert_snapshot_created,
    create_rest_client,
    is_community,
    set_client_tenant,
)
from cloudify_cli.utils import get_deployment_environment_execution
from cloudify_cli.constants import CREATE_DEPLOYMENT
from cloudify_rest_client.exceptions import UserUnauthorizedError


HELLO_WORLD_URL = 'https://github.com/cloudify-cosmo/cloudify-hello-world-example/archive/master.zip'  # noqa
BASE_ID = 'helloworld'
BLUEPRINT_ID = '{base}_bp'.format(base=BASE_ID)
DEPLOYMENT_ID = '{base}_dep'.format(base=BASE_ID)
NOINSTALL_BLUEPRINT_ID = '{base}_noinstall_bp'.format(base=BASE_ID)
NOINSTALL_DEPLOYMENT_ID = '{base}_noinstall_dep'.format(base=BASE_ID)
SNAPSHOT_ID = 'testsnapshot'
# This is used purely for testing that plugin restores have occurred.
# Any plugin should work.
TEST_PLUGIN_URL = 'http://repository.cloudifysource.org/cloudify/wagons/cloudify-openstack-plugin/2.0.1/cloudify_openstack_plugin-2.0.1-py27-none-linux_x86_64-centos-Core.wgn'  # noqa
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
    'master'
)


def get_multi_tenant_versions_list():
    if is_community():
        # Community only works single tenanted
        return ()
    else:
        return MULTI_TENANT_MANAGERS


def upgrade_agents(cfy, manager, logger):
    logger.info('Upgrading agents')
    args = [] if is_community() else ['--all-tenants']
    cfy.agents.install(args)


def remove_and_check_deployments(hello_vms, manager, logger,
                                 tenants=('default_tenant',),
                                 with_prefixes=False):
    for tenant in tenants:
        _log(
            'Uninstalling hello world deployments from manager',
            logger,
            tenant,
        )
        _log(
            'Found deployments: {deployments}'.format(
                deployments=', '.join(get_deployments_list(manager, tenant)),
            ),
            logger,
            tenant,
        )
        with set_client_tenant(manager, tenant):
            if with_prefixes:
                deployment_id = tenant + DEPLOYMENT_ID
            else:
                deployment_id = DEPLOYMENT_ID
            execution = manager.client.executions.start(
                deployment_id,
                'uninstall',
            )

        logger.info('Waiting for uninstall to finish')
        wait_for_execution(
            manager,
            execution,
            logger,
            tenant,
        )
        _log('Uninstalled deployments', logger, tenant)

    assert_hello_worlds(hello_vms, installed=False, logger=logger)


def stop_manager(manager, logger):
    logger.info('Stopping {version} manager..'.format(
        version=manager.image_type))
    manager.stop()


def create_helloworld_just_deployment(manager, logger, tenant=None):
    """
        Upload an AWS hello world blueprint and create a deployment from it.
        This is used for checking that plugins installed from source work as
        expected.
    """
    upload_helloworld(
        manager,
        'test-ec2-bp.yaml',
        NOINSTALL_BLUEPRINT_ID,
        tenant,
        logger,
    )

    inputs = {
        'image_id': 'does not matter',
    }

    deploy_helloworld(
        manager,
        inputs,
        NOINSTALL_BLUEPRINT_ID,
        NOINSTALL_DEPLOYMENT_ID,
        tenant,
        logger,
    )


def upload_helloworld(manager, blueprint, blueprint_id, tenant, logger):
    version = manager.image_type
    logger.info(
        'Uploading blueprint {blueprint} from archive {archive} as {name} '
        'for manager version {version}'.format(
            blueprint=blueprint,
            archive=HELLO_WORLD_URL,
            name=blueprint_id,
            version=version,
        )
    )
    with set_client_tenant(manager, tenant):
        manager.client.blueprints.publish_archive(
            HELLO_WORLD_URL,
            blueprint_id,
            blueprint,
        )


def deploy_helloworld(manager, inputs, blueprint_id,
                      deployment_id, tenant, logger):
    version = manager.image_type
    _log(
        'Deploying {deployment} on {version} manager'.format(
            deployment=deployment_id,
            version=version,
        ),
        logger,
        tenant,
    )
    with set_client_tenant(manager, tenant):
        manager.client.deployments.create(
            blueprint_id,
            deployment_id,
            inputs,
            skip_plugins_validation=True,
        )

        creation_execution = get_deployment_environment_execution(
            manager.client, deployment_id, CREATE_DEPLOYMENT)
    logger.info('Waiting for execution environment')
    wait_for_execution(
        manager,
        creation_execution,
        logger,
        tenant,
    )
    logger.info('Deployment environment created')


def upload_and_install_helloworld(attributes, logger, manager, target_vm,
                                  tmpdir, prefix='', tenant=None):
    assert not is_hello_world(target_vm), (
        'Hello world blueprint already installed!'
    )
    version = manager.image_type
    _log(
        'Uploading helloworld blueprint to {version} manager'.format(
            version=version,
        ),
        logger,
        tenant,
    )
    blueprint_id = prefix + BLUEPRINT_ID
    deployment_id = prefix + DEPLOYMENT_ID
    inputs = {
        'server_ip': target_vm.ip_address,
        'agent_user': attributes.centos_7_username,
        'agent_private_key_path': manager.remote_private_key_path,
    }
    upload_helloworld(
        manager,
        'test-bp.yaml',
        blueprint_id,
        tenant,
        logger,
    )

    deploy_helloworld(
        manager,
        inputs,
        blueprint_id,
        deployment_id,
        tenant,
        logger,
    )

    with set_client_tenant(manager, tenant):
        execution = manager.client.executions.start(
            deployment_id,
            'install')
    logger.info('Waiting for installation to finish')
    wait_for_execution(
        manager,
        execution,
        logger,
        tenant,
    )
    assert is_hello_world(target_vm), (
        'Hello world blueprint did not install correctly.'
    )


class ExecutionWaiting(Exception):
    """
    raised by `wait_for_execution` if it should be retried
    """
    pass


class ExecutionFailed(Exception):
    """
    raised by `wait_for_execution` if a bad state is reached
    """
    pass


def retry_if_not_failed(exception):
    return not isinstance(exception, ExecutionFailed)


@retrying.retry(
    stop_max_delay=5 * 60 * 1000,
    wait_fixed=100000,
    retry_on_exception=retry_if_not_failed,
)
def wait_for_execution(manager, execution, logger, tenant=None,
                       change_manager_password=True):
    _log(
        'Getting workflow execution [id={execution}]'.format(
            execution=execution['id'],
        ),
        logger,
        tenant,
    )
    try:
        with set_client_tenant(manager, tenant):
            execution = manager.client.executions.get(execution['id'])
    except UserUnauthorizedError:
        if (manager_supports_users_in_snapshot_creation(manager) and
                change_manager_password):
            # This will happen on a restore with modified users
            change_rest_client_password(manager, CHANGED_ADMIN_PASSWORD)

    logger.info('- execution.status = %s', execution.status)
    if execution.status not in execution.END_STATES:
        raise ExecutionWaiting(execution.status)
    if execution.status != execution.TERMINATED:
        raise ExecutionFailed(execution.status)
    return execution


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


def is_hello_world(vm):
    with vm.ssh() as fabric_ssh:
        result = fabric_ssh.sudo(
            'curl localhost:8080 || echo "Curl failed."'
        ).stdout
        return 'Cloudify Hello World' in result


def assert_hello_worlds(hello_vms, installed, logger):
    """
        Assert that all hello worlds are saying hello if installed is True.

        If installed is False then instead confirm that they are all not
        saying hello, to allow for detection of uninstall workflow failures.

        :param hello_vms: A list of all hello world VMs.
        :param installed: Boolean determining whether we are checking for
                          hello world deployments that are currently
                          installed (True) or not installed (False).
        :param logger: A logger to provide useful output.
    """
    logger.info('Confirming that hello world services are {state}.'.format(
        state='running' if installed else 'not running',
    ))
    for hello_vm in hello_vms:
        if installed:
            assert is_hello_world(hello_vm), (
                'Hello world was not running after restore.'
            )
        else:
            assert not is_hello_world(hello_vm), (
                'Hello world blueprint did not uninstall correctly.'
            )
    logger.info('Hello world services are in expected state.')


def create_snapshot(manager, snapshot_id, attributes, logger):
    logger.info('Creating snapshot on manager {image_name}'
                .format(image_name=manager.image_name))
    manager.client.snapshots.create(
        snapshot_id=snapshot_id,
        include_credentials=True,
        include_logs=True,
        include_events=True
    )
    if manager_supports_users_in_snapshot_creation(manager):
        password = CHANGED_ADMIN_PASSWORD
    else:
        password = 'admin'
    assert_snapshot_created(manager, snapshot_id, password)


def manager_supports_users_in_snapshot_creation(manager):
    """Premium managers starting 4.2 support users in snapshot creation."""
    return not is_community()


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


def restore_snapshot(manager, snapshot_id, cfy, logger,
                     restore_certificates=False, force=False,
                     wait_for_post_restore_commands=True,
                     wait_timeout=20, change_manager_password=True,
                     cert_path=None):
    # Show the snapshots, to aid troubleshooting on failures
    manager.use(cert_path=cert_path)
    cfy.snapshots.list()

    logger.info('Restoring snapshot on latest manager..')
    restore_execution = manager.client.snapshots.restore(
        snapshot_id,
        restore_certificates=restore_certificates,
        force=force
    )

    _assert_restore_status(manager)

    try:
        wait_for_execution(
            manager,
            restore_execution,
            logger,
            change_manager_password=change_manager_password)
    except ExecutionFailed:
        # See any errors
        cfy.executions.list(['--include-system-workflows'])
        raise

    # wait a while to allow the restore-snapshot post-workflow commands to run
    if wait_for_post_restore_commands:
        sleep(wait_timeout)


def prepare_credentials_tests(cfy, logger, manager):
    manager.use()

    change_salt(manager, 'this_is_a_test_salt', cfy, logger)

    logger.info('Creating test user')
    create_user('testuser', 'testpass', cfy)
    logger.info('Updating admin password')
    update_admin_password(CHANGED_ADMIN_PASSWORD, cfy)
    change_rest_client_password(manager, CHANGED_ADMIN_PASSWORD)


def update_credentials(cfy, logger, manager):
    logger.info('Changing to modified admin credentials')
    change_profile_credentials('admin', CHANGED_ADMIN_PASSWORD, cfy,
                               validate=False)
    change_rest_client_password(manager, CHANGED_ADMIN_PASSWORD)


def check_credentials(cfy, logger, manager):
    logger.info('Checking test user still works')
    test_user('testuser', 'testpass', cfy, logger, CHANGED_ADMIN_PASSWORD)


def change_rest_client_password(manager, new_password):
    manager.client = create_rest_client(manager.ip_address,
                                        tenant='default_tenant',
                                        password=new_password)


def create_user(username, password, cfy):
    cfy.users.create(['-r', 'sys_admin', '-p', password, username])


def change_password(username, password, cfy):
    cfy.users(['set-password', '-p', password, username])


def test_user(username, password, cfy, logger, admin_password='admin'):
    logger.info('Checking {user} can log in.'.format(user=username))
    # This command will fail noisily if the credentials don't work
    cfy.profiles.set(['-u', username, '-p', password])

    # Now revert to the admin user
    cfy.profiles.set(['-u', 'admin', '-p', admin_password])


def change_profile_credentials(username, password, cfy, validate=True):
    cmd = ['-u', username, '-p', password]
    if not validate:
        cmd.append('--skip-credentials-validation')
    cfy.profiles.set(cmd)


def update_admin_password(new_password, cfy):
    # Update the admin user on the manager then in our profile
    change_password('admin', new_password, cfy)
    change_profile_credentials('admin', new_password, cfy)


def get_security_conf(manager):
    with manager.ssh() as fabric_ssh:
        output = fabric_ssh.sudo('cat /opt/manager/rest-security.conf').stdout
    # No real error checking here; the old manager shouldn't be able to even
    # start the rest service if this file isn't json.
    return json.loads(output)


def change_salt(manager, new_salt, cfy, logger):
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
    fix_admin_account(manager, new_salt, cfy)

    logger.info('Hash updated.')


def fix_admin_account(manager, salt, cfy):
    new_hash = generate_admin_password_hash('admin', salt)
    new_hash = new_hash.replace('$', '\\$')

    with manager.ssh() as fabric_ssh:
        fabric_ssh.run(
            'sudo -u postgres psql cloudify_db -t -c '
            '"UPDATE users SET password=\'{new_hash}\' '
            'WHERE id=0"'.format(
                new_hash=new_hash,
            ),
        )

    # This will confirm that the hash change worked... or it'll fail.
    change_profile_credentials('admin', 'admin', cfy)


def generate_admin_password_hash(admin_password, salt):
    # Flask password hash generation approach for Cloudify 4.x where x<=2
    pwd_hmac = base64.b64encode(
        # Encodes put in to keep hmac happy with unicode strings
        hmac.new(salt.encode('utf-8'), admin_password.encode('utf-8'),
                 hashlib.sha512).digest()
    ).decode('ascii')

    # This ctx is nothing to do with a cloudify ctx.
    pass_ctx = CryptContext(schemes=['pbkdf2_sha256'])
    return pass_ctx.encrypt(pwd_hmac)


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


def upload_test_plugin(manager, logger, tenant=None):
    _log('Uploading test plugin', logger, tenant)
    with set_client_tenant(manager, tenant):
        manager.client.plugins.upload(TEST_PLUGIN_URL)
        manager.wait_for_all_executions()


def get_plugins_list(manager, tenant=None):
    with set_client_tenant(manager, tenant):
        return [
            (
                item['package_name'],
                item['package_version'],
                item['distribution'],
            )
            for item in manager.client.plugins.list()
        ]


def get_deployments_list(manager, tenant=None):
    with set_client_tenant(manager, tenant):
        return [
            item['id'] for item in manager.client.deployments.list()
        ]


def get_secrets_list(manager, tenant=None):
    with set_client_tenant(manager, tenant):
        return [
            item['key'] for item in manager.client.secrets.list()
        ]


def get_nodes(manager, tenant=None):
    with set_client_tenant(manager, tenant):
        return manager.client.nodes.list()


def hosts(
        request, cfy, ssh_key, module_tmpdir, attributes, logger,
        hello_count, install_dev_tools=True):

    manager_types = [request.param, 'master']
    hello_vms = ['centos' for i in range(hello_count)]
    instances = [
        get_image(mgr_type)
        for mgr_type in manager_types + hello_vms
    ]

    hosts = TestHosts(
        cfy, ssh_key, module_tmpdir,
        attributes, logger, instances=instances, request=request,
        upload_plugins=False)
    hosts.create()

    # gcc and python-devel are needed to build most of our infrastructure
    # plugins.
    # As we need to test from source installation of plugins, we must have
    # these packages installed.
    # We'll iterate over only the old and new managers (managers[0] and
    # managers[1].
    # The hello_world VMs don't need these so we won't waste time installing
    # them.
    for manager in instances[:2]:
        with manager.ssh() as fabric_ssh:
            fabric_ssh.sudo('yum -y -q install gcc')
            fabric_ssh.sudo('yum -y -q install python-devel')

    with instances[0].ssh() as fabric_ssh:
        fabric_ssh.sudo('systemctl restart cloudify-restservice')

    instances[0].verify_services_are_running()

    return hosts


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
