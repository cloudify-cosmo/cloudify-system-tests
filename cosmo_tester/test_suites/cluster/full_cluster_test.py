import time

import retrying

from cloudify.constants import BROKER_PORT_SSL
from cloudify.exceptions import TimeoutException
from cloudify.cluster_status import ServiceStatus, NodeServiceStatus
from cloudify_rest_client.exceptions import CloudifyClientError

from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import set_client_tenant


def test_full_cluster(full_cluster, logger, ssh_key, test_config):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster

    example = get_example_deployment(mgr1, ssh_key, logger, 'full_cluster',
                                     test_config)
    example.inputs['server_ip'] = mgr1.ip_address
    example.upload_and_verify_install()

    logger.info('Creating snapshot')
    snapshot_id = 'cluster_test_snapshot'
    create_snapshot(mgr1, snapshot_id, logger)

    logger.info('Restoring snapshot')
    restore_snapshot(mgr2, snapshot_id, logger, force=True,
                     cert_path=mgr2.local_ca)

    check_managers(mgr1, mgr2, example)


# This is to confirm that we work with a single DB endpoint set (e.g. on a
# PaaS).
# It is not intended that a single external DB be used in production.
def test_cluster_single_db(cluster_with_single_db, logger, ssh_key,
                           test_config):
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db

    example = get_example_deployment(mgr1, ssh_key, logger, 'cluster_1_db',
                                     test_config)
    example.inputs['server_ip'] = mgr1.ip_address
    example.upload_and_verify_install()

    logger.info('Creating snapshot')
    snapshot_id = 'cluster_test_snapshot'
    create_snapshot(mgr1, snapshot_id, logger)

    logger.info('Restoring snapshot')
    restore_snapshot(mgr2, snapshot_id, logger, force=True,
                     cert_path=mgr2.local_ca)

    check_managers(mgr1, mgr2, example)


def test_queue_node_failover(cluster_with_single_db, logger,
                             module_tmpdir, ssh_key, test_config):
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db

    example = get_example_deployment(mgr1, ssh_key, logger, 'queue_failover',
                                     test_config)
    example.inputs['server_ip'] = mgr1.ip_address
    example.upload_and_verify_install()
    _validate_cluster_and_agents(mgr1, example.tenant)
    agent_broker_ip1 = _verify_agent_broker_connection_and_get_broker_ip(
        example.example_host,
    )

    # stop the rabbitmq service in the agent's broker node
    agent_broker = None
    for broker in [broker1, broker2, broker3]:
        if broker.private_ip_address == agent_broker_ip1:
            agent_broker = broker
            break
    with agent_broker.ssh() as broker_ssh:
        broker_ssh.run('sudo service cloudify-rabbitmq stop')

    # the agent should now pick another broker
    _validate_cluster_and_agents(mgr1, example.tenant,
                                 expected_broker_status='Degraded')
    agent_broker_ip2 = _verify_agent_broker_connection_and_get_broker_ip(
        example.example_host,
    )
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
        _wait_for_healthy_broker_cluster(mgr1.client)
        with agent_broker.ssh() as broker_ssh:
            broker_ssh.run('sudo service cloudify-rabbitmq stop')
        agent_broker_ip = new_agent_broker_ip
        new_agent_broker_ip = (
           _verify_agent_broker_connection_and_get_broker_ip(
                example.example_host,
           )
        )
        if new_agent_broker_ip in restarted_broker_ips:
            restarted_broker_connected = True
        assert len(restarted_broker_ips) < 3

    assert restarted_broker_connected

    example.uninstall()


def test_manager_node_failover(cluster_with_lb, logger, module_tmpdir,
                               ssh_key, test_config):
    broker, db, mgr1, mgr2, mgr3, lb = cluster_with_lb

    lb.wait_for_manager()

    example = get_example_deployment(mgr1, ssh_key, logger,
                                     'manager_failover', test_config)
    example.inputs['server_ip'] = mgr1.ip_address
    example.upload_and_verify_install()
    _validate_cluster_and_agents(lb, example.tenant)

    # get agent's manager node
    agent_host = lb.client.agents.list(_all_tenants=True)[0]['id']

    lb.client._client.cert = lb.local_ca
    with set_client_tenant(lb.client, example.tenant):
        node_instances = lb.client.node_instances.list().items
    agent_manager_ip = None
    for instance in node_instances:
        if instance.id == agent_host:
            agent_manager_ip = instance.runtime_properties['cloudify_agent'][
                'file_server_url'].split('/')[2].split(':')[0]
            break
    agent_mgr = None
    for manager in [mgr1, mgr2, mgr3]:
        if manager.private_ip_address == agent_manager_ip:
            agent_mgr = manager
            break

    # stop the manager connected to the agent
    agent_mgr.run_command('cfy_manager stop')

    lb.wait_for_manager()
    time.sleep(5)  # wait 5 secs for status reporter to poll
    _validate_cluster_and_agents(lb, example.tenant,
                                 expected_managers_status='Degraded')

    # restart the manager connected to the agent
    with agent_mgr.ssh() as manager_ssh:
        manager_ssh.run('cfy_manager start')

    time.sleep(5)
    _validate_cluster_and_agents(lb, example.tenant)

    # stop two managers
    mgr2.run_command('cfy_manager stop')
    mgr3.run_command('cfy_manager stop')

    lb.wait_for_manager()
    time.sleep(5)
    _validate_cluster_and_agents(lb, example.tenant,
                                 expected_managers_status='Degraded')

    example.uninstall()


def test_workflow_resume_manager_failover(minimal_cluster,
                                          logger, ssh_key, test_config):
    broker, db, mgr1, mgr2 = minimal_cluster

    example = get_example_deployment(mgr1, ssh_key, logger,
                                     'workflow_resume_manager_failover',
                                     test_config, using_agent=False)
    example.inputs['wait'] = 60
    example.upload_blueprint()
    example.create_deployment()
    execution_start_time = time.time()
    with set_client_tenant(mgr1.client, example.tenant):
        exec_id = mgr1.client.executions.start(example.deployment_id,
                                               'install').id
    time.sleep(3)   # wait for mgmtworker to get the execution
    executing_manager = None
    other_manager = None
    for manager in [mgr1, mgr2]:
        try:
            manager.run_command('grep {} /var/log/cloudify/mgmtworker/'
                                'mgmtworker.log'.format(exec_id))
        except Exception:
            continue
        executing_manager = manager
        other_manager = ({mgr1, mgr2} - {executing_manager}).pop()

    # kill the first manager and  wait for execution to finish
    executing_manager.run_command('cfy_manager stop')
    manager_failover_time = time.time()
    assert manager_failover_time - execution_start_time < 60
    time.sleep(60)

    # verify on the second manager that the execution completed successfully
    with set_client_tenant(other_manager.client, example.tenant):
        executions = other_manager.client.executions.list()
    installs = [execution for execution in executions
                if execution['workflow_id'] == 'install']
    assert len(installs) == 1
    assert installs[0]['status'] == 'completed'


def _wait_for_healthy_broker_cluster(client, timeout=15):
    for _ in range(timeout):
        time.sleep(2)
        cluster_status = client.cluster_status.get_status()
        if cluster_status['services']['broker']['status'] == \
                ServiceStatus.HEALTHY:
            return
    raise TimeoutException


def _validate_cluster_and_agents(manager,
                                 tenant,
                                 expected_broker_status='OK',
                                 expected_managers_status='OK'):
    validate_agents = manager.run_command(
        'cfy agents validate --tenant-name {}'.format(tenant)).stdout
    assert 'Task succeeded' in validate_agents

    cluster_status = manager.client.cluster_status.get_status()['services']
    manager_status = manager.client.manager.get_status()
    assert manager_status['status'] == ServiceStatus.HEALTHY
    assert cluster_status['manager']['status'] == expected_managers_status
    assert cluster_status['db']['status'] == ServiceStatus.HEALTHY
    assert cluster_status['broker']['status'] == expected_broker_status


def _verify_agent_broker_connection_and_get_broker_ip(agent_node):
    agent_netstat_result = agent_node.run_command(
        'netstat -na | grep {port}'.format(port=BROKER_PORT_SSL),
    ).stdout.split('\n')

    connection_established = False
    for line in agent_netstat_result:
        if 'ESTABLISHED' in line:
            connection_established = True
            return line.split(':')[-2].split(' ')[-1]
    assert connection_established   # error if no connection on rabbit port


def test_cluster_status(full_cluster, logger, module_tmpdir):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster

    _assert_cluster_status(mgr1.client)
    _verify_status_when_syncthing_inactive(mgr1, mgr2, logger)
    _verify_status_when_postgres_inactive(db1, db2, logger, mgr1.client)
    _verify_status_when_rabbit_inactive(broker1, broker2, broker3, logger,
                                        mgr1.client)


def _verify_status_when_syncthing_inactive(mgr1, mgr2, logger):
    logger.info('Stopping syncthing on one of the manager nodes')
    mgr1.run_command('systemctl stop cloudify-syncthing', use_sudo=True)

    # Syncthing is down, mgr1 in Fail state
    manager_status = mgr1.client.manager.get_status()
    assert manager_status['status'] == ServiceStatus.FAIL
    assert manager_status['services']['File Sync Service']['status'] == \
        NodeServiceStatus.INACTIVE
    time.sleep(10)

    # mgr2 is the last healthy manager in a cluster
    cluster_status = mgr2.client.cluster_status.get_status()
    manager_service = cluster_status['services']['manager']
    assert cluster_status['status'] == ServiceStatus.DEGRADED
    assert manager_service['status'] == ServiceStatus.DEGRADED
    manager_status = mgr2.client.manager.get_status()
    assert manager_status['status'] == ServiceStatus.HEALTHY
    assert manager_status['services']['File Sync Service']['status'] == \
        NodeServiceStatus.ACTIVE

    # Back to healthy cluster
    logger.info('Starting syncthing on the failed manager')
    mgr1.run_command('systemctl start cloudify-syncthing', use_sudo=True)
    time.sleep(10)
    _assert_cluster_status(mgr1.client)


def _verify_status_when_postgres_inactive(db1, db2, logger, client):
    logger.info('Stopping one of the db nodes')
    db1.run_command('systemctl stop patroni etcd', use_sudo=True)
    db_service = _assert_cluster_status_after_db_changes(
        ServiceStatus.DEGRADED, logger, client,
    )
    assert db_service['nodes'][db1.hostname]['status'] == ServiceStatus.FAIL

    logger.info('Stopping another db node')
    db2.run_command('systemctl stop patroni etcd', use_sudo=True)

    try:
        client.cluster_status.get_status()
    except CloudifyClientError:
        logger.info('DB cluster is not healthy, must have minimum 2 nodes')
        pass

    logger.info('Starting Patroni and Etcd on the failed db nodes')
    db1.run_command('systemctl start patroni etcd', use_sudo=True)
    db2.run_command('systemctl start patroni etcd', use_sudo=True)
    _assert_cluster_status_after_db_changes(ServiceStatus.HEALTHY, logger,
                                            client)


def _verify_status_when_rabbit_inactive(broker1, broker2, broker3, logger,
                                        client):
    logger.info('Stopping one of the rabbit nodes')
    broker1.run_command('systemctl stop cloudify-rabbitmq', use_sudo=True)
    time.sleep(10)

    cluster_status = client.cluster_status.get_status()
    broker_service = cluster_status['services']['broker']
    assert cluster_status['status'] == ServiceStatus.DEGRADED
    assert broker_service['status'] == ServiceStatus.DEGRADED
    assert broker_service['nodes'][broker1.hostname]['status'] == \
        ServiceStatus.FAIL
    manager_status = client.manager.get_status()
    assert manager_status['status'] == ServiceStatus.HEALTHY

    logger.info('Stopping the other rabbit nodes')
    broker2.run_command('systemctl stop cloudify-rabbitmq', use_sudo=True)
    broker3.run_command('systemctl stop cloudify-rabbitmq', use_sudo=True)
    time.sleep(10)

    cluster_status = client.cluster_status.get_status()
    assert cluster_status['status'] == 'Fail'
    assert cluster_status['services']['broker']['status'] == ServiceStatus.FAIL
    assert cluster_status['services']['manager']['status'] == \
        ServiceStatus.FAIL
    assert cluster_status['services']['db']['status'] == ServiceStatus.HEALTHY
    manager_status = client.manager.get_status()
    assert manager_status['status'] == 'Fail'


# It sometimes takes a little time for the status reporter to return healthy
# We'll allow up to a minute in case of slow test platform
@retrying.retry(stop_max_attempt_number=30, wait_fixed=2000)
def _assert_cluster_status(client):
    assert client.cluster_status.get_status()[
        'status'] == ServiceStatus.HEALTHY


@retrying.retry(stop_max_attempt_number=4, wait_fixed=10000)
def _assert_cluster_status_after_db_changes(status, logger, client):
    logger.info('Check cluster status after DB changes')
    cluster_status = client.cluster_status.get_status()
    db_service = cluster_status['services']['db']
    assert cluster_status['status'] == status
    assert db_service['status'] == status
    manager_status = client.manager.get_status()
    assert manager_status['status'] == ServiceStatus.HEALTHY
    logger.info('The cluster status is valid after DB changes')
    return db_service
