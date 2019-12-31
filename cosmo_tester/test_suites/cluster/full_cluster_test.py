import json
import time

from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)
from cosmo_tester.framework.examples.hello_world import centos_hello_world
from cosmo_tester.framework.test_hosts import _CloudifyManager
from cloudify.constants import BROKER_PORT_SSL
from cloudify.exceptions import TimeoutException


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
    configure_brokers_status_reporter([mgr1, mgr2],
                                      [broker1, broker2, broker3])

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


def configure_brokers_status_reporter(managers, brokers):
    manager_ips = ' '.join([mgr.private_ip_address for mgr in managers])
    tokens = managers[0].run_command(
        'cfy_manager status-reporter get-tokens --json')
    tokens = json.loads(tokens.strip('\033[0m'))
    broker_token = tokens['broker_status_reporter']

    status_config_command = \
        'cfy_manager status-reporter configure --token {token} ' \
        '--ca-path {ca_path} --managers-ip {manager_ips}'
    for broker in brokers:
        broker.run_command(status_config_command.format(
            token=broker_token,
            manager_ips=manager_ips,
            ca_path=broker.remote_ca
        ))
