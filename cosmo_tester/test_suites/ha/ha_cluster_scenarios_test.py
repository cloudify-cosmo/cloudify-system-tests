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


import csv
import pytest
import time

import fabric.network

from cosmo_tester.framework.examples.hello_world import (
    centos_hello_world,
    windows_hello_world
)
from cosmo_tester.framework.test_hosts import TestHosts
from cosmo_tester.framework.util import (
    prepare_and_get_test_tenant,
    set_client_tenant
)
from . import skip_community
from . import ha_helper

REPEAT_COUNT = 2

# Skip all tests in this module if we're running community tests,
# using the pytestmark magic variable name
pytestmark = skip_community


@pytest.fixture(scope='function', params=[3])
def hosts(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a HA cluster from an image in rackspace OpenStack."""
    logger.info('Creating HA cluster of %s managers', request.param)
    hosts = TestHosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=request.param, request=request)

    for manager in hosts.instances[1:]:
        manager.upload_plugins = False

    try:
        hosts.create()
        ha_helper.setup_cluster(hosts.instances, cfy, logger)
        yield hosts
    finally:
        hosts.destroy()


@pytest.fixture(scope='function')
def ha_hello_worlds(cfy, hosts, attributes, ssh_key, tmpdir, logger):
    # Pick a manager to operate on, and trust the cluster to work with us
    manager = hosts.instances[0]

    hws = []
    tenant = prepare_and_get_test_tenant(
        'clusterhello_centos', manager, cfy)
    hw = centos_hello_world(
        cfy, manager, attributes, ssh_key, logger, tmpdir,
        tenant=tenant, suffix='centos',
    )
    hws.append(hw)
    win_tenant = prepare_and_get_test_tenant(
        'clusterhello_win', manager, cfy,)
    win_hw = windows_hello_world(
        cfy, manager, attributes, ssh_key, logger, tmpdir,
        tenant=win_tenant, suffix='win',
    )
    hws.append(win_hw)
    yield hws
    for hw in hws:
        if hw.cleanup_required:
            logger.info('Cleaning up hello world...')
            manager.use()
            hw.cleanup()


def test_data_replication(cfy, hosts, ha_hello_worlds, logger):
    manager1 = hosts.instances[0]
    ha_helper.delete_active_profile()
    manager1.use()
    ha_helper.verify_nodes_status(manager1, logger)
    _test_hellos(ha_hello_worlds, install=True)

    logger.info('Manager %s resources', manager1.ip_address)
    m1_blueprints_list = cfy.blueprints.list()
    m1_deployments_list = cfy.deployments.list()
    m1_plugins_list = cfy.plugins.list()

    for manager in hosts.instances[1:]:
        ha_helper.set_active(manager, cfy, logger)
        ha_helper.delete_active_profile()
        manager.use()
        ha_helper.verify_nodes_status(manager, logger)
        logger.info('Manager %s resources', manager.ip_address)
        assert m1_blueprints_list == cfy.blueprints.list()
        assert m1_deployments_list == cfy.deployments.list()
        assert m1_plugins_list == cfy.plugins.list()

    ha_helper.set_active(manager1, cfy, logger)
    ha_helper.delete_active_profile()
    manager1.use()


def test_sync_set_active(cfy, hosts, ha_hello_worlds, logger):
    manager1 = hosts.instances[0]
    ha_helper.delete_active_profile()
    manager1.use()
    ha_helper.verify_nodes_status(manager1, logger)

    nodes_data = {}
    for manager in hosts.instances:
        with manager.ssh() as ssh:
            nodes_data[manager.private_ip_address] = {
                'follow_count': _get_follow_count(ssh),
                'promote_count': _get_promote_count(ssh),
            }

    for manager in hosts.instances[1:] + hosts.instances * 2:
        ha_helper.set_active(manager, cfy, logger)
        with manager.ssh() as ssh:
            follow_count = _get_follow_count(ssh)
            promote_count = _get_promote_count(ssh)
            db_replicas = _get_replicas(ssh)
        previous = nodes_data[manager.private_ip_address]
        assert follow_count == previous['follow_count']
        assert promote_count == previous['promote_count'] + 1
        assert len(db_replicas) == 2
        assert set(db_replicas.values()) == {'sync', 'potential'}
        previous['promote_count'] = promote_count

        for replica in hosts.instances:
            if replica is manager:
                continue
            with replica.ssh() as replica_ssh:
                replica_follow_count = _get_follow_count(replica_ssh)
                replica_promote_count = _get_promote_count(replica_ssh)
                replica_db_replicas = _get_replicas(replica_ssh)
            replica_data = nodes_data[replica.private_ip_address]
            # assert replica_follow_count == replica_data['follow_count'] + 1
            # assert replica_promote_count == replica_data['promote_count']
            assert not replica_db_replicas
            replica_data['follow_count'] = replica_follow_count
        time.sleep(30)
        ha_helper.delete_active_profile()
        manager.use()
        ha_helper.verify_nodes_status(manager, logger)


def test_sync_disconnect(cfy, hosts, logger):
    manager1 = hosts.instances[0]
    ha_helper.delete_active_profile()
    manager1.use()
    ha_helper.verify_nodes_status(manager1, logger)

    nodes_data = {}
    for manager in hosts.instances:
        with manager.ssh() as ssh:
            nodes_data[manager.private_ip_address] = {
                'follow_count': _get_follow_count(ssh),
                'promote_count': _get_promote_count(ssh),
            }
    with hosts.instances[0].ssh() as ssh:
        replicas = _get_replicas(ssh)
        for ip, state in replicas.items():
            nodes_data[ip]['state'] = state
    current_master = hosts.instances[0]
    for manager in hosts.instances[1:] + hosts.instances * REPEAT_COUNT:
        _iptables(current_master, hosts.instances)
        new_master = ha_helper.wait_leader_election(
            [n for n in hosts.instances if n is not current_master],
            logger)
        sync_replicas = {
            private_ip for private_ip, v in nodes_data.items()
            if v.get('state') == 'sync'}
        assert len(sync_replicas) == 1
        previous_master = current_master
        current_master = new_master
        ha_helper.verify_nodes_status(current_master, logger)
        _iptables(previous_master, hosts.instances, flag='-D')
        ha_helper.wait_nodes_online(hosts.instances, logger)
        with current_master.ssh() as ssh:
            follow_count = _get_follow_count(ssh)
            promote_count = _get_promote_count(ssh)
            db_replicas = _get_replicas(ssh)
        previous = nodes_data[current_master.private_ip_address]
        assert follow_count == previous['follow_count']
        assert promote_count == previous['promote_count'] + 1
        assert len(db_replicas) == 2
        assert set(db_replicas.values()) == {'sync', 'potential'}
        previous['promote_count'] = promote_count
        for v in nodes_data.values():
            v.pop('state', None)
        for ip, state in db_replicas.items():
            nodes_data[ip]['state'] = state
        for replica in hosts.instances:
            if replica is current_master:
                continue
            with replica.ssh() as replica_ssh:
                replica_follow_count = _get_follow_count(replica_ssh)
                replica_promote_count = _get_promote_count(replica_ssh)
                replica_db_replicas = _get_replicas(replica_ssh)
            replica_data = nodes_data[replica.private_ip_address]
#            assert replica_follow_count == replica_data['follow_count'] + 1
#            assert replica_promote_count == replica_data['promote_count']
            assert not replica_db_replicas
            replica_data['follow_count'] = replica_follow_count


def test_partition_replica(cfy, hosts, logger):
    manager1 = hosts.instances[0]
    ha_helper.delete_active_profile()
    manager1.use()
    ha_helper.verify_nodes_status(manager1, logger)

    nodes_data = {}
    for manager in hosts.instances:
        with manager.ssh() as ssh:
            nodes_data[manager.private_ip_address] = {
                'follow_count': _get_follow_count(ssh),
                'promote_count': _get_promote_count(ssh),
            }
    by_private_ip = {n.private_ip_address: n for n in hosts.instances}
    with hosts.instances[0].ssh() as ssh:
        replicas = _get_replicas(ssh)
    assert len(replicas) == 2
    sync_ip = next(ip for ip, state in replicas.items() if state == 'sync')
    async_ip = next(ip for ip, state in replicas.items()
                    if state in {'async', 'potential'})
    sync_replica = by_private_ip[sync_ip]
    async_replica = by_private_ip[async_ip]

    _iptables(async_replica, hosts.instances)
    time.sleep(20)
    with hosts.instances[0].ssh() as ssh:
        replicas = _get_replicas(ssh)
    assert len(replicas) == 1
    assert replicas[sync_ip] == 'sync'
    _iptables(async_replica, hosts.instances, flag='-D')

    time.sleep(60)
    with hosts.instances[0].ssh() as ssh:
        replicas = _get_replicas(ssh)
    assert len(replicas) == 2

    _iptables(sync_replica, hosts.instances)
    time.sleep(20)
    with hosts.instances[0].ssh() as ssh:
        replicas = _get_replicas(ssh)
    assert len(replicas) == 1
    assert replicas[async_ip] == 'sync'
    _iptables(sync_replica, hosts.instances, flag='-D')

    time.sleep(60)
    with hosts.instances[0].ssh() as ssh:
        replicas = _get_replicas(ssh)
    assert len(replicas) == 2


def test_sync_failover(cfy, hosts, logger):
    manager1 = hosts.instances[0]
    ha_helper.delete_active_profile()
    manager1.use()
    ha_helper.verify_nodes_status(manager1, logger)

    nodes_data = {}
    for manager in hosts.instances:
        with manager.ssh() as ssh:
            nodes_data[manager.private_ip_address] = {
                'follow_count': _get_follow_count(ssh),
                'promote_count': _get_promote_count(ssh),
            }
    by_private_ip = {n.private_ip_address: n for n in hosts.instances}
    with hosts.instances[0].ssh() as ssh:
        replicas = _get_replicas(ssh)
    assert len(replicas) == 2
    sync_ip = next(ip for ip, state in replicas.items() if state == 'sync')
    async_ip = next(ip for ip, state in replicas.items()
                    if state in {'async', 'potential'})
    first_master = hosts.instances[0]
    sync_replica = by_private_ip[sync_ip]
    async_replica = by_private_ip[async_ip]

    _iptables(async_replica, hosts.instances)
    time.sleep(20)
    _iptables(first_master, hosts.instances)
    time.sleep(20)

    _iptables(async_replica, [sync_replica], flag='-D')
    new_leader = ha_helper.wait_leader_election(
        [sync_replica, async_replica], logger)
    ha_helper.verify_nodes_status(new_leader, logger)

    with new_leader.ssh() as ssh:
        replicas = _get_replicas(ssh)
    assert replicas == {async_ip: 'sync'}

    _iptables(async_replica, [first_master], flag='-D')
    _iptables(first_master, hosts.instances, flag='-D')
    time.sleep(60)

    with new_leader.ssh() as ssh:
        replicas = _get_replicas(ssh)
    assert len(replicas) == 2


def test_failover_while_disconnected(cfy, hosts, logger):
    manager1, manager2, manager3 = hosts.instances
    ha_helper.delete_active_profile()
    manager1.use()
    ha_helper.verify_nodes_status(manager1, logger)

    for _ in range(10):
        _iptables(manager2, [manager1, manager3])
        ha_helper.set_active(manager3, cfy, logger, wait=False)
        ha_helper.wait_nodes_online(hosts.instances, logger, count=2)
        _iptables(manager2, [manager1, manager3], flag='-D')
        ha_helper.wait_nodes_online(hosts.instances, logger)
        ha_helper.verify_nodes_status(manager3, logger)
        _iptables(manager2, [manager1, manager3])
        ha_helper.set_active(manager1, cfy, logger, wait=False)
        ha_helper.wait_nodes_online(hosts.instances, logger, count=2)
        _iptables(manager2, [manager1, manager3], flag='-D')
        ha_helper.wait_nodes_online(hosts.instances, logger)
        ha_helper.verify_nodes_status(manager1, logger)


def _get_follow_count(ssh):
    return int(ssh.sudo(
        'grep -c "switch_master_db: following" '
        '/var/log/cloudify/cloudify-cluster.log || true'))


def _get_promote_count(ssh):
    return int(ssh.sudo(
        'grep -c "promote_master_db: promoting" '
        '/var/log/cloudify/cloudify-cluster.log || true'))


def _get_replicas(ssh):
    lines = ssh.sudo(
        'cd / && sudo -upostgres psql --port 15432 -c '
        '"copy (select client_addr, sync_state from pg_stat_replication) '
        'to stdout with (format csv)"')
    entries = list(csv.reader(lines.split('\n')))
    if not entries or not any(entries):
        return {}
    return dict(entries)


def _iptables(manager, block_nodes, flag='-A'):
    with manager.ssh() as _fabric:
        for other_host in block_nodes:
            if other_host is manager:
                continue
            _fabric.sudo('iptables {0} INPUT -s {1} -j DROP'
                         .format(flag, other_host.private_ip_address))
            _fabric.sudo('iptables {0} OUTPUT -d {1} -j DROP'
                         .format(flag, other_host.private_ip_address))
    fabric.network.disconnect_all()


def test_heal_after_failover(cfy, hosts, ha_hello_worlds, logger):
    manager1 = hosts.instances[0]
    manager1.use()
    ha_helper.verify_nodes_status(manager1, logger)
    _test_hellos(ha_hello_worlds, install=True)

    manager2 = hosts.instances[-1]
    ha_helper.set_active(manager2, cfy, logger)
    manager2.use()

    # The tricky part we're validating here is that the agent install script
    # will use the new master's IP, instead of the old one
    for hello_world in ha_hello_worlds:
        _heal_hello_world(cfy, manager2, hello_world)
    for hello_world in ha_hello_worlds:
        hello_world.uninstall()


def _get_host_instance_id(manager, hello_world):
    with set_client_tenant(manager, hello_world.tenant):
        # We should only have a single instance of the `vm` node
        instance = manager.client.node_instances.list(
            deployment_id=hello_world.deployment_id,
            node_id='vm'
        )[0]
    return instance.id


def _heal_hello_world(cfy, manager, hello_world):
    instance_id = _get_host_instance_id(manager, hello_world)
    cfy.executions.start('heal',
                         '-d', hello_world.deployment_id,
                         '-t', hello_world.tenant,
                         '-p', 'node_instance_id={0}'.format(instance_id))


def _test_hellos(hello_worlds, install=False):
    for hello_world in hello_worlds:
        hello_world.upload_blueprint()
        if install:
            hello_world.create_deployment()
            hello_world.install()
