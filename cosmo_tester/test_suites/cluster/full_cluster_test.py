import json
import time
from os import path

import sh

from cloudify.constants import BROKER_PORT_SSL
from cloudify.exceptions import TimeoutException
from cloudify.cluster_status import ServiceStatus, NodeServiceStatus

from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)
from cosmo_tester.framework.examples.hello_world import centos_hello_world
from cosmo_tester.framework.test_hosts import _CloudifyManager


def test_full_cluster(full_cluster, logger, attributes, cfy):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster

    logger.info('Creating snapshot')
    snapshot_id = 'cluster_test_snapshot'
    create_snapshot(mgr1, snapshot_id, attributes, logger)

    logger.info('Restoring snapshot')
    restore_snapshot(mgr2, snapshot_id, cfy, logger, force=True,
                     cert_path=mgr2.local_ca)

    check_managers(mgr1, mgr2)


# This is to confirm that we work with a single DB endpoint set (e.g. on a
# PaaS).
# It is not intended that a single external DB be used in production.
def test_cluster_single_db(cluster_with_single_db, logger, attributes, cfy):
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db

    logger.info('Creating snapshot')
    snapshot_id = 'cluster_test_snapshot'
    create_snapshot(mgr1, snapshot_id, attributes, logger)

    logger.info('Restoring snapshot')
    restore_snapshot(mgr2, snapshot_id, cfy, logger, force=True,
                     cert_path=mgr2.local_ca)

    check_managers(mgr1, mgr2)


def test_queue_node_failover(cluster_with_single_db, logger,
                             module_tmpdir, attributes, ssh_key, cfy):
    hello_world = prepare_cluster_with_agent(
        cluster_with_single_db, logger,
        module_tmpdir, attributes, ssh_key, cfy
    )
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db
    validate_cluster_and_agents(mgr1)
    agent_broker_ip1 = verify_agent_broker_connection_and_get_broker_ip(mgr1)

    # stop the rabbitmq service in the agent's broker node
    agent_broker = None
    for broker in [broker1, broker2, broker3]:
        if broker.private_ip_address == agent_broker_ip1:
            agent_broker = broker
            break
    with agent_broker.ssh() as broker_ssh:
        broker_ssh.run('sudo service cloudify-rabbitmq stop')

    # the agent should now pick another broker
    validate_cluster_and_agents(mgr1, expected_broker_status='Degraded')
    agent_broker_ip2 = \
        verify_agent_broker_connection_and_get_broker_ip(mgr1)
    assert agent_broker_ip2 != agent_broker_ip1

    # The following asserts that the agent will reconnect to a stopped and
    # restarted broker.

    restarted_broker_connected = False
    restarted_broker_ips = []
    agent_broker_ip = agent_broker_ip1
    new_agent_broker_ip = agent_broker_ip2

    while not restarted_broker_connected:
        with agent_broker.ssh() as broker_ssh:
            broker_ssh.run('sudo service cloudify-rabbitmq start')
        restarted_broker_ips.append(agent_broker_ip)
        # stop another broker
        for broker in [broker1, broker2, broker3]:
            if broker.private_ip_address == new_agent_broker_ip:
                agent_broker = broker
                break
        wait_for_healthy_broker_cluster(mgr1)
        with agent_broker.ssh() as broker_ssh:
            broker_ssh.run('sudo service cloudify-rabbitmq stop')
        agent_broker_ip = new_agent_broker_ip
        new_agent_broker_ip = \
            verify_agent_broker_connection_and_get_broker_ip(mgr1)
        if new_agent_broker_ip in restarted_broker_ips:
            restarted_broker_connected = True
        assert len(restarted_broker_ips) < 3

    assert restarted_broker_connected

    # finally, uninstall the hello world
    mgr1.run_command(
        'cfy executions start uninstall -d {deployment_id} -t {tenant} '
        '--timeout 900'.format(deployment_id=hello_world.deployment_id,
                               tenant=hello_world.tenant))


def wait_for_healthy_broker_cluster(mgr_node, timeout=15):
    for _ in range(timeout):
        time.sleep(1)
        cluster_status = mgr_node.run_command('cfy cluster status --json')
        cluster_status = json.loads(cluster_status.strip('\033[0m'))
        if cluster_status['services']['broker']['status'] == 'OK':
            return
    raise TimeoutException


def prepare_cluster_with_agent(cluster_with_single_db, logger,
                               module_tmpdir, attributes, ssh_key, cfy):
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db
    logger.info('Installing a deployment with agents')
    hello_world = centos_hello_world(cfy, mgr1, attributes, ssh_key,
                                     logger, module_tmpdir)

    _CloudifyManager.upload_necessary_files(mgr1)
    _CloudifyManager.upload_necessary_files(mgr2)
    _CloudifyManager.upload_plugin(mgr1,
                                   mgr1._attributes.default_openstack_plugin)

    # Install a hello world deployment.
    # The test cluster has no outer network access so mgr1.use() won't do, so I
    # use a workaround to run the following functions with the manager's client
    hello_world.cfy = mgr1.client
    hello_world.upload_blueprint()
    hello_world.create_deployment()
    mgr1.run_command(
        'cfy executions start install -d {deployment_id} -t {tenant} '
        '--timeout 900'.format(deployment_id=hello_world.deployment_id,
                               tenant=hello_world.tenant))
    hello_world.verify_installation()
    return hello_world


def validate_cluster_and_agents(mgr_node, expected_manager_status='OK',
                                expected_broker_status='OK'):
    validate_agents = mgr_node.run_command('cfy agents validate')
    assert 'Task succeeded' in validate_agents

    manager_status = mgr_node.run_command('cfy status --json')
    cluster_status = mgr_node.run_command('cfy cluster status --json')
    cluster_status = json.loads(cluster_status.strip('\033[0m'))['services']
    assert json.loads(manager_status.strip('\033[0m'))['status'] == 'OK'
    assert cluster_status['manager']['status'] == expected_manager_status
    assert cluster_status['db']['status'] == 'OK'
    assert cluster_status['broker']['status'] == expected_broker_status


def verify_agent_broker_connection_and_get_broker_ip(mgr_node):
    netstat_check_command = \
        'sudo ssh -i /etc/cloudify/key.pem -o StrictHostKeyChecking=no ' \
        'centos@{agent_ip} netstat -na | grep {broker_port}'

    agent_ip = mgr_node.client.agents.list().items[0]['ip']
    agent_netstat_result = mgr_node.run_command(netstat_check_command.format(
        agent_ip=agent_ip, broker_port=BROKER_PORT_SSL)).split('\n')
    connection_established = False
    for line in agent_netstat_result:
        if 'ESTABLISHED' in line:
            connection_established = True
            return line.split(':')[-2].split(' ')[-1]
    assert connection_established   # error if no connection on rabbit port


def test_cluster_status(full_cluster, logger, cfy, module_tmpdir):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster
    cert_path = path.join(module_tmpdir, 'ca.crt')
    mgr1.get_remote_file(mgr1.remote_ca, cert_path)
    mgr1.use(cert_path=cert_path)

    _assert_cluster_status(cfy)
    _verify_status_when_syncthing_inactive(mgr1, mgr2, cert_path, logger, cfy)
    _verify_status_when_postgres_inactive(db1, db2, logger, cfy)
    _verify_status_when_rabbit_inactive(broker1, broker2, broker3, logger, cfy)


def _verify_status_when_syncthing_inactive(mgr1, mgr2, cert_path, logger, cfy):
    logger.info('Stopping syncthing on one of the manager nodes')
    mgr1.run_command('systemctl stop cloudify-syncthing', use_sudo=True)

    # Syncthing is down, mgr1 in Fail state
    manager_status = _get_manager_status(cfy)
    assert manager_status['status'] == ServiceStatus.FAIL
    assert manager_status['services']['File Sync Service']['status'] == \
        NodeServiceStatus.INACTIVE
    time.sleep(10)

    # mgr2 is the last healthy manager in a cluster
    mgr2.use(cert_path=cert_path)
    cluster_status = _get_cluster_status(cfy)
    manager_service = cluster_status['services']['manager']
    assert cluster_status['status'] == ServiceStatus.DEGRADED
    assert manager_service['status'] == ServiceStatus.DEGRADED
    manager_status = _get_manager_status(cfy)
    assert manager_status['status'] == ServiceStatus.HEALTHY
    assert manager_status['services']['File Sync Service']['status'] == \
        NodeServiceStatus.ACTIVE

    # Back to healthy cluster
    logger.info('Starting syncthing on the failed manager')
    mgr1.run_command('systemctl start cloudify-syncthing', use_sudo=True)
    time.sleep(10)
    _assert_cluster_status(cfy)


def _verify_status_when_postgres_inactive(db1, db2, logger, cfy):
    logger.info('Stopping one of the db nodes')
    db1.run_command('systemctl stop patroni etcd', use_sudo=True)
    time.sleep(10)

    cluster_status = _get_cluster_status(cfy)
    db_service = cluster_status['services']['db']
    assert cluster_status['status'] == ServiceStatus.DEGRADED
    assert db_service['status'] == ServiceStatus.DEGRADED
    assert db_service['nodes'][db1.hostname]['status'] == ServiceStatus.FAIL
    manager_status = _get_manager_status(cfy)
    assert manager_status['status'] == ServiceStatus.HEALTHY

    logger.info('Stopping another db node')
    db2.run_command('systemctl stop patroni etcd', use_sudo=True)

    try:
        _get_cluster_status(cfy)
    except sh.ErrorReturnCode_1:
        logger.info('DB cluster is not healthy, must have minimum 2 nodes')
        pass

    logger.info('Starting Patroni and Etcd on the failed db nodes')
    db1.run_command('systemctl start patroni etcd', use_sudo=True)
    db2.run_command('systemctl start patroni etcd', use_sudo=True)
    time.sleep(10)
    _assert_cluster_status(cfy)


def _verify_status_when_rabbit_inactive(broker1, broker2, broker3, logger,
                                        cfy):
    logger.info('Stopping one of the rabbit nodes')
    broker1.run_command('systemctl stop cloudify-rabbitmq', use_sudo=True)
    time.sleep(10)

    cluster_status = _get_cluster_status(cfy)
    broker_service = cluster_status['services']['broker']
    assert cluster_status['status'] == ServiceStatus.DEGRADED
    assert broker_service['status'] == ServiceStatus.DEGRADED
    assert broker_service['nodes'][broker1.hostname]['status'] == \
        ServiceStatus.FAIL
    manager_status = _get_manager_status(cfy)
    assert manager_status['status'] == ServiceStatus.HEALTHY

    logger.info('Stopping the other rabbit nodes')
    broker2.run_command('systemctl stop cloudify-rabbitmq', use_sudo=True)
    broker3.run_command('systemctl stop cloudify-rabbitmq', use_sudo=True)
    time.sleep(10)

    cluster_status = _get_cluster_status(cfy)
    assert cluster_status['status'] == 'Fail'
    assert cluster_status['services']['broker']['status'] == ServiceStatus.FAIL
    assert cluster_status['services']['manager']['status'] == \
        ServiceStatus.FAIL
    assert cluster_status['services']['db']['status'] == ServiceStatus.HEALTHY
    manager_status = _get_manager_status(cfy)
    assert manager_status['status'] == 'Fail'


def _assert_cluster_status(cfy):
    cluster_status = _get_cluster_status(cfy)
    assert cluster_status['status'] == ServiceStatus.HEALTHY


def _get_cluster_status(cfy):
    return json.loads(cfy.cluster.status('--json').stdout[4:-8])


def _get_manager_status(cfy):
    return json.loads(cfy.status('--json').stdout[4:-8])
