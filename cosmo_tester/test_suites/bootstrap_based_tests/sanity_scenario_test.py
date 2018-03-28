########
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

import time
import pytest
import os
import json

from cosmo_tester.framework.test_hosts import TestHosts

from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    download_snapshot,
    upload_snapshot,
    restore_snapshot,
    upgrade_agents,
    delete_manager
)

from cosmo_tester.test_suites.ha.ha_helper \
    import HighAvailabilityHelper as ha_helper


@pytest.fixture(scope='module')
def managers(cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps 3 Cloudify managers on a VM in Rackspace OpenStack."""

    hosts = TestHosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=3)

    for manager in hosts.instances[1:]:
        manager.upload_plugins = False

    try:
        hosts.create()
        yield hosts.instances
    finally:
        hosts.destroy()


def test_sanity_scenario(managers,
                         cfy,
                         logger,
                         tmpdir,
                         attributes):
    manager1 = managers[0]
    manager2 = managers[1]
    manager3 = managers[2]

    blueprint_yaml = 'simple-blueprint.yaml'
    blueprint_name = deployment_name = "nodecellar"
    user_name = "sanity_user"
    user_pass = "user123"
    tenant_name = "tenant"
    tenant_role = "user"

    inputs = {
        'host_ip': manager1.ip_address,
        'agent_user': attributes.centos_7_username,
        'agent_private_key_path':
            manager1.remote_private_key_path,
    }

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
    _create_secrets(cfy, logger, manager1)

    _install_blueprint(cfy, logger, blueprint_name, deployment_name,
                       blueprint_yaml, inputs)

    logger.info('Use second manager')
    cfy.profiles.set('-u', 'admin', '-p', 'admin', '-t', 'default_tenant')
    manager2.use()

    logger.info('Joining HA cluster')
    _join_cluster(cfy, manager1, manager2)

    logger.info('Set passive manager')
    ha_helper.set_active(manager2, cfy, logger)

    snapshot_id = 'SNAPSHOT_ID'
    local_snapshot_path = str(tmpdir / 'snap.zip')
    logger.info('Creating snapshot')
    create_snapshot(manager2, snapshot_id, attributes, logger)
    download_snapshot(manager2, local_snapshot_path, snapshot_id, logger)

    manager3.use()

    logger.info('Uploading and restoring snapshot')
    upload_snapshot(manager3, local_snapshot_path, snapshot_id, logger)
    restore_snapshot(manager3, snapshot_id, cfy, logger)
    # wait a while to allow the restore-snapshot post-workflow commands to run
    time.sleep(30)

    logger.info('Upgrading agents')
    upgrade_agents(cfy, manager3, logger)

    _set_sanity_user(cfy, logger, tenant_name, user_name, user_pass)

    _uninstall_blueprint(cfy, logger, blueprint_name, deployment_name)

    delete_manager(manager1, logger)


def _set_key_pair(manager1):
    with manager1.ssh() as fabric_ssh:
        fabric_ssh.sudo('cp {0} {1}'.format(manager1.remote_private_key_path,
                                            '/etc/cloudify/ssh_key'))
        fabric_ssh.sudo('chown cfyuser:cfyuser ssh_key')


def _uninstall_blueprint(cfy, logger, blueprint_name, deployment_name):
    logger.info('Uninstalling execution')
    cfy.executions.start.uninstall('-d', deployment_name)

    logger.info('Deleting deployment')
    cfy.deployments.delete(deployment_name)

    logger.info('Deleting blueprint')
    cfy.blueprint.delete(blueprint_name)


def _install_blueprint(cfy, logger, blueprint_name, deployment_name,
                       blueprint_yaml, inputs):
    blueprint_path = os.path.abspath(os.path.join
                                     (os.path.dirname(__file__), '..', '..',
                                      'resources/blueprints/sanity-scenario-'
                                      'nodecellar/nodecellar-example.zip'))

    logger.info('Uploading blueprint')
    cfy.blueprint.upload(blueprint_path, '-b', blueprint_name, '-l', 'private',
                         '-n', blueprint_yaml)

    logger.info('Creating deployment')
    cfy.deployments.create('-b', blueprint_name, deployment_name,
                           '-l', 'private', '-i', json.dumps(inputs))

    logger.info('Installing execution')
    cfy.executions.start.install('-d', deployment_name)


def _create_secrets(cfy, logger, manager1):
    logger.info('Creating secret agent_user as blueprint input')
    cfy.secrets.create('user', '-s', 'centos')

    logger.info('Creating secret agent_private_key_path as blueprint input')
    cfy.secrets.create('key', '-s', manager1.remote_private_key_path)

    logger.info('Creating secret host_ip as blueprint input')
    cfy.secrets.create('ip', '-s', manager1.ip_address)


def _manage_tenants(cfy, logger, user_name, user_pass, tenant_name, role):
    logger.info('Creating new user')
    cfy.users.create(user_name, '-p', user_pass)

    logger.info('Starting Tenant')
    cfy.tenants.create(tenant_name)

    logger.info('Adding user to tenant')
    cfy.tenants('add-user', user_name, '-t', tenant_name, '-r', role)

    _set_sanity_user(cfy, logger, tenant_name, user_name, user_pass)


def _set_sanity_user(cfy, logger, tenant_name, user_name, user_pass):
    logger.info('Set to sanity_user')
    cfy.profiles.set('-u', user_name, '-p', user_pass, '-t', tenant_name)


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
