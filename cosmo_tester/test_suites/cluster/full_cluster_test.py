import json

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

    import pydevd
    pydevd.settrace('192.168.9.43', port=53200, stdoutToServer=True,
                    stderrToServer=True)

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
    _validate_cluster_and_agents(mgr1)
    new_agent_broker_ip = \
        _verify_agent_broker_connection_and_get_broker_ip(mgr1)
    assert new_agent_broker_ip != agent_broker_ip

    new_agent_broker = None
    for broker in [broker1, broker2, broker3]:
        if broker.private_ip_address == new_agent_broker_ip:
            new_agent_broker = broker
            break

    import pydevd
    pydevd.settrace('192.168.9.43', port=53200, stdoutToServer=True,
                    stderrToServer=True)

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
    # TODO: should happen IN PARALLEL to the above. verify that

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


def _validate_cluster_and_agents(mgr_node):
    validate_agents = mgr_node.run_command('cfy agents validate')
    assert 'Task succeeded' in validate_agents

    manager_status = mgr_node.run_command('cfy status --json')
    # cluster_status = mgr_node.run_command('cfy cluster status --json')
    assert json.loads(manager_status.strip('\033[0m'))['status'] == 'OK'
    # assert json.loads(cluster_status.strip('\033[0m'))['status'] == 'OK'
    # --- all brokers status @ 'Fail' [Sandy hasn't included it in the
    # fixtures yet]    # TODO: Awaiting a fix from Sandy


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
