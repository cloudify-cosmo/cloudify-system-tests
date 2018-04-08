# from time import sleep
# from os.path import join
import pytest
import os

from cosmo_tester.framework.test_hosts import TestHosts
# from cosmo_tester.framework import util
# from cosmo_tester.test_suites.ha.ha_helper \
#     import HighAvailabilityHelper as ha_helper


from cosmo_tester.test_suites.ha.ha_helper \
    import HighAvailabilityHelper as ha_helper


@pytest.fixture(scope='module')
def image_based_manager(
        cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    hosts = TestHosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=2)
    try:
        hosts.create()
        hosts.instances[0].use()
        yield hosts.instances[0]
    finally:
        hosts.destroy()


def test_hello_world(cfy,
                     manager,
                     logger):
    manager1 = manager[0]
    manager2 = manager[1]
    blueprint_yaml = 'simple-blueprint.yaml'
    blueprint_name = deployment_name = "nodecellar"
    user_name = "sanity_user"
    user_pass = "user123"
    tenant_name = "tenant"
    tenant_role = "user"

    logger.info('Using manager1')
    manager1.use()

    logger.info('Cfy version')
    cfy('--version')

    logger.info('Cfy status')
    cfy.status()

    logger.info('Starting HA cluster')
    _start_cluster(cfy, manager1)

    # Create user, tenant and set the new user
    _manage_tenants(cfy, logger, user_name, user_pass, tenant_name,
                    tenant_role)

    # Creating secrets
    _create_secrets(cfy, logger, manager)

    _install_blueprint(cfy, logger, blueprint_name, deployment_name, blueprint_yaml)

    logger.info('Use second manager')
    manager2.use()

    logger.info('Joining HA cluster')
    _join_cluster(cfy, manager1, manager2)

    logger.info('Set passive manager')
    ha_helper.set_active(manager2, cfy, logger)

    _set_sanity_user(cfy, logger, tenant_name, user_name, user_pass)

    _uninstall_blueprint(cfy, logger, blueprint_name, deployment_name)


def _manage_tenants(cfy, logger, user_name, user_pass, tenant_name, role):

    logger.info('Creating new user')
    cfy.users.create(user_name, '-p', user_pass)

    logger.info('Starting Tenant')
    cfy.tenants.create(tenant_name)

    logger.info('Adding user to tenant')
    cfy.tenants('add-user', user_name, '-t', tenant_name, '-r', role)  # fix


def _create_secrets(cfy, logger, manager1):

    logger.info('Creating secret agent_user as blueprint input')
    cfy.secrets.create('user', '-s', 'centos')

    logger.info('Creating secret agent_private_key_path as blueprint input')
    cfy.secrets.create('key', '-s', manager1.remote_private_key_path)

    logger.info('Creating secret host_ip as blueprint input')
    cfy.secrets.create('ip', '-s', manager1.ip_address)


def _install_blueprint(cfy, logger, blueprint_name, deployment_name, blueprint_yaml):
    blueprint_path = os.path.abspath(os.path.join
                                     (os.path.dirname(__file__), '..', '..',
                                      'resources/blueprints/sanity-scenario-'
                                      'nodecellar/cloudify-nodecellar-example-master.zip'))

    logger.info('Uploading blueprint')
    cfy.blueprint.upload(blueprint_path, '-b', blueprint_name, '-l', 'private', '-n', blueprint_yaml)
    cfy.blueprint.list()

    logger.info('Creating deployment')
    cfy.deployments.create('-b', blueprint_name, deployment_name,
                           '-l', 'private', '-i', 'agent_user=user', '-i',
                           'agent_private_key_path=key', '-i', 'host_ip=ip')
    cfy.deployments.list()

    logger.info('Installing execution')
    cfy.executions.start.install('-d', deployment_name)
    cfy.executions.list()


def _start_cluster(cfy, manager1):
    cfy.cluster.start(timeout=600,
                      cluster_host_ip=manager1.private_ip_address,
                      cluster_node_name=manager1.ip_address)


def _join_cluster(cfy, manager1, manager2):
    cfy.cluster.join(manager1.ip_address,
                     timeout=600,
                     cluster_host_ip=manager2.private_ip_address,
                     cluster_node_name=manager2.ip_address)
    cfy.cluster.nodes.list()


def _set_sanity_user(cfy, logger, tenant_name, user_name, user_pass):

    logger.info('Set to sanity_user')
    cfy.profiles.set('-u', user_name, '-p', user_pass, '-t', tenant_name)


def _uninstall_blueprint(cfy, logger, blueprint_name, deployment_name):
    try:
        logger.info('Uninstalling execution')
        cfy.executions.start.uninstall('-d', deployment_name)
    except:
        cfy.profiles.set('-u', 'admin', '-p', 'admin', '-t', 'default_tenant')
        cfy.executions.start.uninstall('-d', deployment_name)

    logger.info('Deleting deployment')
    cfy.deployments.delete(deployment_name)

    logger.info('Deleting blueprint')
    cfy.blueprint.delete(blueprint_name)
