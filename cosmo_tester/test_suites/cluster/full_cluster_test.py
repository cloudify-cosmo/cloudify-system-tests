import json
import time

from cloudify.exceptions import CommandExecutionException

from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)
from cosmo_tester.framework.examples.hello_world import centos_hello_world
from cosmo_tester.framework.test_hosts import _CloudifyManager
from cloudify.constants import BROKER_PORT_SSL


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
    hello_world = _prepare_cluster_with_agent(
        cluster_with_single_db, logger,
        module_tmpdir, attributes, ssh_key, cfy
    )
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db
    _validate_cluster_and_agents(mgr1)
    agent_broker_ip = _verify_agent_broker_connection_and_get_broker_ip(mgr1)

    # stop the rabbitmq service in the agent's broker node
    agent_broker = None
    for broker in [broker1, broker2, broker3]:
        if broker.private_ip_address == agent_broker_ip:
            agent_broker = broker
            break
    with agent_broker.ssh() as broker_ssh:
        broker_ssh.run('sudo service cloudify-rabbitmq stop')

    # the agent should now pick another broker
    _validate_cluster_and_agents(mgr1, expected_broker_status='Degraded')
    new_agent_broker_ip = \
        _verify_agent_broker_connection_and_get_broker_ip(mgr1)
    assert new_agent_broker_ip != agent_broker_ip

    new_agent_broker = None
    for broker in [broker1, broker2, broker3]:
        if broker.private_ip_address == new_agent_broker_ip:
            new_agent_broker = broker
            break

    # import pydevd
    # pydevd.settrace('192.168.9.43', port=53200, stdoutToServer=True,
    #                 stderrToServer=True)

    # spin up 3 deployments
    for i in range(3):
        deployment_id = '{0}-{1}'.format(hello_world.deployment_id, i)
        mgr1.client.deployments.create(
            deployment_id=deployment_id,
            blueprint_id=hello_world.blueprint_id,
            inputs=hello_world.inputs)
        mgr1.run_command(
            'cfy executions start install -d {deployment_id} -t {tenant} '
            '--timeout 900'.format(deployment_id=deployment_id,
                                   tenant=hello_world.tenant))

    # bring the stopped rabbit back up
    with agent_broker.ssh() as broker_ssh:
        broker_ssh.run('sudo service cloudify-rabbitmq start')

    # verify that the resurrected rabbit shares the load
    with new_agent_broker.ssh() as broker_ssh:
        for broker in [broker1, broker2, broker3]:
            num_queues = broker_ssh.run(
                'sudo -u rabbitmq rabbitmqctl -n rabbit@{0} list_queues'
                ' | wc -l'.format(broker.hostname))
            assert num_queues > 0

    # finally, uninstall all the hello worlds
    mgr1.run_command(
        'cfy executions start uninstall -d {deployment_id} -t {tenant} '
        '--timeout 900'.format(deployment_id=hello_world.deployment_id,
                               tenant=hello_world.tenant))
    for i in range(3):
        deployment_id = '{0}-{1}'.format(hello_world.deployment_id, i)
        mgr1.run_command(
            'cfy executions start uninstall -d {deployment_id} -t {tenant} '
            '--timeout 900'.format(deployment_id=deployment_id,
                                   tenant=hello_world.tenant))


def test_manager_node_failover(cluster_with_single_db, logger,
                               module_tmpdir, attributes, ssh_key, cfy):
    hello_world = _prepare_cluster_with_agent(
        cluster_with_single_db, logger,
        module_tmpdir, attributes, ssh_key, cfy
    )
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db
    _validate_cluster_and_agents(mgr1)

    # get agent's manager ip
    agent_host = mgr1.client.agents.list().items[0].host_id
    node_instances = mgr1.client.node_instances.list().items
    agent_manager_ip = None
    for instance in node_instances:
        if instance.id == agent_host:
            agent_manager_ip = instance.runtime_properties['cloudify_agent'][
                'file_server_url'].split('/')[2].split(':')[0]
            break

    # stop the rest service in the manager node connected to the agent
    agent_mgr = None
    spare_mgr = None
    for manager in [mgr1, mgr2]:
        if manager.private_ip_address == agent_manager_ip:
            agent_mgr = manager
        else:
            spare_mgr = manager

    with agent_mgr.ssh() as manager_ssh:
        manager_ssh.run('sudo service cloudify-restservice stop')
        manager_ssh.run('sudo shutdown -h now &')

    # wait till the machine shuts down
    for _ in range(60):
        try:
            time.sleep(1)
            spare_mgr.run_command('ping -c 1 {0}'.format(agent_manager_ip))
        except CommandExecutionException:
            break

    # cluster status should be degraded, since we're left with only one manager
    _validate_cluster_and_agents(spare_mgr, expected_manager_status='Degraded')

    # finally, uninstall the hello world deployment
    spare_mgr.run_command(
        'cfy executions start uninstall -d {deployment_id} -t {tenant} '
        '--timeout 900'.format(deployment_id=hello_world.deployment_id,
                               tenant=hello_world.tenant))


def _prepare_cluster_with_agent(cluster_with_single_db, logger,
                                module_tmpdir, attributes, ssh_key, cfy):
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db

    _configure_brokers_status_reporter([mgr1, mgr2],
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


def _validate_cluster_and_agents(mgr_node,
                                 expected_manager_status='OK',
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


def _verify_agent_broker_connection_and_get_broker_ip(mgr_node):
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


def _configure_brokers_status_reporter(managers, brokers):
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
