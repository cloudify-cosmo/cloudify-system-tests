########
# Copyright (c) 2019 Cloudify Platform Ltd. All rights reserved
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

from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    download_snapshot,
    upload_snapshot,
    restore_snapshot,
    verify_services_status
)
from ..ha.ha_helper import (
    wait_nodes_online,
    failover_cluster,
    fail_and_recover_cluster,
    reverse_cluster_test,
    toggle_cluster_node,
    _test_hellos
)
from cosmo_tester.framework.cfy_helper import (
    create_and_add_user_to_tenant,
    create_secrets,
    set_admin_user
)


USER_NAME = "test_user"
USER_PASS = "testuser123"
TENANT_NAME = "tenant"


@pytest.mark.parametrize('distributed_installation', [{'cluster': True}],
                         indirect=True)
def test_distributed_installation_ha(distributed_installation,
                                     cfy,
                                     logger,
                                     distributed_ha_hello_worlds):
    logger.info('Testing HA functionality for cluster with an external '
                'database and an external message queue')
    # Update cfy-profile with all managers in the cluster
    cfy.cluster.update_profile()

    failover_cluster(cfy, distributed_installation,
                     distributed_ha_hello_worlds, logger)
    reverse_cluster_test(distributed_installation, logger)

    # Test doesn't affect the cluster - no need to reverse
    fail_and_recover_cluster(cfy, distributed_installation, logger)


@pytest.mark.parametrize('distributed_installation', [{'cluster': True}],
                         indirect=True)
def test_distributed_installation_ha_remove_from_cluster(
        distributed_installation, cfy, logger, distributed_ha_hello_worlds):
    cfy.cluster.update_profile()

    _test_hellos(distributed_ha_hello_worlds)

    manager_1 = distributed_installation.instances[0]
    nodes_to_check = list(distributed_installation.instances)
    for manager in distributed_installation.instances[1:]:
        logger.info('Removing the manager %s from HA cluster',
                    manager.ip_address)
        # The hostname of the machine should be the same as in the managers
        # table
        cfy.cluster.remove(manager.hostname)
        nodes_to_check.remove(manager)

    manager_1.use()

    _test_hellos(distributed_ha_hello_worlds, delete_blueprint=True)


@pytest.mark.parametrize('distributed_installation', [{'cluster': True}],
                         indirect=True)
def test_distributed_installation_delete_from_cluster(
        distributed_installation, cfy, logger, distributed_ha_hello_worlds):
    cfy.cluster.update_profile()

    _test_hellos(distributed_ha_hello_worlds)

    manager_1 = distributed_installation.instances[0]
    for manager in distributed_installation.instances[1:]:
        logger.info('Deleting manager %s', manager.ip_address)
        manager.delete()

    logger.info('Remaining manager %s', manager_1)

    _test_hellos(distributed_ha_hello_worlds, delete_blueprint=True)


@pytest.mark.parametrize('distributed_installation', [{'cluster': True,
                                                       'sanity': True}],
                         indirect=True)
def test_distributed_installation_sanity(distributed_installation,
                                         cfy,
                                         logger,
                                         tmpdir,
                                         attributes,
                                         distributed_nodecellar):
    logger.info('Running Sanity check for cluster with an external database')
    manager1 = distributed_installation.manager
    manager2, manager3 = distributed_installation.joining_managers
    manager_aio = distributed_installation.sanity_manager

    manager1.use()
    cfy.cluster.update_profile()

    logger.info('Cfy version')
    cfy('--version')

    logger.info('Cfy status')
    cfy.status()

    create_and_add_user_to_tenant(cfy, logger)

    set_sanity_user(cfy, manager1, logger)

    # Creating secrets with 'tenant' visibility
    create_secrets(cfy, logger, attributes, manager1)

    distributed_nodecellar.upload_and_verify_install()

    set_admin_user(cfy, manager1, logger)

    # Simulate failover (manager2/3 will be the remaining active managers)
    toggle_cluster_node(manager1, 'nginx', logger, disable=True)

    # Create and download snapshots from the remaining active managers (2 or 3)
    snapshot_id = 'SNAPSHOT_ID'
    local_snapshot_path = str(tmpdir / 'snap.zip')
    logger.info('Creating snapshot')
    create_snapshot(manager2, snapshot_id, attributes, logger)
    download_snapshot(manager2, local_snapshot_path, snapshot_id, logger)

    set_admin_user(cfy, manager_aio, logger)

    # Upload and restore snapshot to the external AIO manager
    logger.info('Uploading and restoring snapshot')
    upload_snapshot(manager_aio, local_snapshot_path, snapshot_id, logger)
    restore_snapshot(manager_aio, snapshot_id, cfy, logger,
                     change_manager_password=False)
    time.sleep(7)
    verify_services_status(manager_aio, logger)

    # wait for agents reconnection
    time.sleep(30)

    # Upgrade agents
    logger.info('Upgrading agents')
    copy_ssl_cert_from_manager_to_tmpdir(manager2, tmpdir)
    args = ['--manager-ip', manager2.private_ip_address,
            '--manager_certificate', str(tmpdir + 'new_manager_cert.txt'),
            '--all-tenants']
    cfy.agents.install(args)

    set_sanity_user(cfy, manager_aio, logger)
    # Verify `agents install` worked as expected
    distributed_nodecellar.uninstall()


def set_sanity_user(cfy,
                    manager,
                    logger,
                    username=USER_NAME,
                    userpass=USER_PASS,
                    tenant_name=TENANT_NAME):
    manager.use()
    logger.info('Using manager `{0}`'.format(manager.ip_address))
    cfy.profiles.set('-u', username, '-p', userpass, '-t', tenant_name)


def copy_ssl_cert_from_manager_to_tmpdir(manager, tmpdir):
    with manager.ssh() as fabric_ssh:
        fabric_ssh.get(
            '/etc/cloudify/ssl/cloudify_internal_ca_cert.pem',
            str(tmpdir + 'new_manager_cert.txt'), use_sudo=True)
