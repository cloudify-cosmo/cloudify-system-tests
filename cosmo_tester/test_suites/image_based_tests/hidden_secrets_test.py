import os
import pytest
import time
from cosmo_tester.framework.test_hosts import TestHosts


@pytest.fixture(scope='module')
def managers(
        cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    hosts = TestHosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=2)

    hosts.instances[1].upload_plugins = False

    try:
        hosts.create()
        yield hosts.instances
    finally:
        hosts.destroy()


def test_hidden_secrets(managers,
                        cfy,
                        logger, tmpdir):

    snap_path = str(tmpdir / 'snap.zip')

    manager1 = managers[0]
    manager2 = managers[1]
    agent_user_key = 'user'
    agent_user_value = 'centos'
    key_pair_key = 'key'
    key_pair_value = manager1.remote_private_key_path
    server_ip_key = 'ip'
    server_ip_value = manager1.ip_address
    user_name1 = 'user1'
    password = 'user123'
    tenant_name = 'default_tenant'
    tenant_role = 'user'
    blueprint_id = 'hello-world'
    blueprint_path = os.path.join(os.path.dirname(__file__), '/home/uri/dev/repos/cloudify-hello-world-example/'
                                                             'secret-blueprint.yaml')
    logger.info('Use manager')
    manager1.use()

    # Testing hidden secret create command by an admin user
    logger.info('Creating secrets by admin')
    _hidden_secret_create(cfy, logger, agent_user_key, agent_user_value)
    _hidden_secret_create(cfy, logger, key_pair_key, key_pair_value)
    _hidden_secret_create(cfy, logger, server_ip_key, server_ip_value)

    logger.info('Creating user and adding to tenant')
    _user_create(cfy, logger, user_name1, password)
    cfy.tenants('add-user', user_name1, '-t', tenant_name, '-r', tenant_role)

    _set_profile(cfy, logger, user_name1, password, tenant_name)

    # Testing that hidden secret can't be seen by non admin user
    logger.info('Get secret value by user1')
    cfy.secrets.list()

    # Installing blueprint
    _install_blueprint(cfy, logger, blueprint_id, blueprint_path)

    _set_profile(cfy, logger, 'admin', 'admin', tenant_name)

    # Snapshot create and download
    cfy.snapshots.create('snap')
    time.sleep(10)
    cfy.snapshots.download('snap', '-o', snap_path)

    manager2.use()

    # Snapshot upload and restore
    cfy.snapshots.upload(snap_path, '-s', 'snap')
    cfy.snapshots.restore('snap')

    # Install agents and uninstall executions
    time.sleep(30)
    cfy.agents.install()
    _set_profile(cfy, logger, user_name1, password, tenant_name)
    cfy.secrets.list()
    cfy.executions.start.uninstall('-d', blueprint_id)


def _user_create(cfy, logger, user_name, user_pass):
    logger.info('Creating new user')
    cfy.users.create(user_name, '-p', user_pass)
    logger.info('user list')
    cfy.users.list()


def _hidden_secret_create(cfy, logger, secret_key, secret_value):
    logger.info('Creating hidden secret')
    cfy.secrets.create(secret_key, '-s', secret_value, '--hidden-value')
    logger.info('secret list')
    cfy.secrets.list()


def _set_profile(cfy, logger, user_name, password, tenant):
    logger.info('Set profile')
    cfy.profiles.set('-u', user_name, '-p', password, '-t', tenant)


def _install_blueprint(cfy, logger, blueprint_id, blueprint_path):
    logger.info('Upload hello-world example blueprint')
    cfy.blueprint.upload(blueprint_path, '-b', blueprint_id)
    cfy.deployments.create(blueprint_id, '-b', blueprint_id, '-i', 'agent_user=user', '-i',
                           'agent_private_key_path=key', '-i', 'server_ip=ip')
    cfy.executions.start.install('-d', blueprint_id)
