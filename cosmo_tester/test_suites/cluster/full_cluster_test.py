import json
import time
from os import path

import sh
import retrying

from cloudify.constants import BROKER_PORT_SSL
from cloudify.exceptions import TimeoutException
from cloudify.cluster_status import ServiceStatus, NodeServiceStatus

from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)
from cosmo_tester.framework.test_hosts import _CloudifyManager
from cosmo_tester.framework.examples.hello_world import centos_hello_world


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

    # cfy commands will use mgr1
    mgr1.use(cert_path=mgr1.local_ca)
    hello_world = _prepare_cluster_with_agent(
        [mgr1, mgr2], logger, module_tmpdir, attributes, ssh_key, cfy
    )
    _validate_cluster_and_agents(cfy)
    agent_broker_ip1 = _verify_agent_broker_connection_and_get_broker_ip(mgr1)

    # stop the rabbitmq service in the agent's broker node
    agent_broker = None
    for broker in [broker1, broker2, broker3]:
        if broker.private_ip_address == agent_broker_ip1:
            agent_broker = broker
            break
    with agent_broker.ssh() as broker_ssh:
        broker_ssh.run('sudo service cloudify-rabbitmq stop')

    # the agent should now pick another broker
    _validate_cluster_and_agents(cfy, expected_broker_status='Degraded')
    agent_broker_ip2 = \
        _verify_agent_broker_connection_and_get_broker_ip(mgr1)
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
        _wait_for_healthy_broker_cluster(cfy)
        with agent_broker.ssh() as broker_ssh:
            broker_ssh.run('sudo service cloudify-rabbitmq stop')
        agent_broker_ip = new_agent_broker_ip
        new_agent_broker_ip = \
            _verify_agent_broker_connection_and_get_broker_ip(mgr1)
        if new_agent_broker_ip in restarted_broker_ips:
            restarted_broker_connected = True
        assert len(restarted_broker_ips) < 3

    assert restarted_broker_connected

    # finally, uninstall the hello world
    mgr1.run_command(
        'cfy executions start uninstall -d {deployment_id} -t {tenant} '
        '--timeout 900'.format(deployment_id=hello_world.deployment_id,
                               tenant=hello_world.tenant))


def test_manager_node_failover(cluster_with_lb, logger, module_tmpdir,
                               attributes, ssh_key, cfy):
    broker, db, mgr1, mgr2, mgr3, lb = cluster_with_lb

    lb.use(cert_path=lb.local_ca)
    _wait_for_cfy_node_to_start_serving(cfy)  # where the cfy node = the LB

    hello_world = _prepare_cluster_with_agent(
        [mgr1, mgr2, mgr3], logger, module_tmpdir, attributes, ssh_key, cfy
    )
    _validate_cluster_and_agents(cfy)

    # get agent's manager node
    agent_host = json.loads(cfy.agents.list('--json').stdout)[0]['id']
    lb.client._client.cert = lb.local_ca
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
    with agent_mgr.ssh() as manager_ssh:
        manager_ssh.run('cfy_manager stop')

    _wait_for_cfy_node_to_start_serving(cfy)
    time.sleep(5)  # wait 5 secs for status reporter to poll
    _validate_cluster_and_agents(cfy, expected_managers_status='Degraded')

    # restart the manager connected to the agent
    with agent_mgr.ssh() as manager_ssh:
        manager_ssh.run('cfy_manager start')

    time.sleep(5)
    _validate_cluster_and_agents(cfy)

    # stop two managers
    with mgr2.ssh() as manager_ssh:
        manager_ssh.run('cfy_manager stop')
    with mgr3.ssh() as manager_ssh:
        manager_ssh.run('cfy_manager stop')

    _wait_for_cfy_node_to_start_serving(cfy)
    time.sleep(5)
    _validate_cluster_and_agents(cfy, expected_managers_status='Degraded')

    # finally, uninstall the hello world
    mgr1.run_command(
        'cfy executions start uninstall -d {deployment_id} -t {tenant} '
        '--timeout 900'.format(deployment_id=hello_world.deployment_id,
                               tenant=hello_world.tenant))


def _wait_for_cfy_node_to_start_serving(cfy, timeout=15):
    for _ in range(timeout):
        time.sleep(1)
        try:
            cfy.status()
            return
        except Exception:
            continue
    raise TimeoutException


def test_workflow_resume_manager_failover(minimal_cluster, cfy):
    broker, db, mgr1, mgr2 = minimal_cluster
    mgr1.use(cert_path=mgr1.local_ca)
    plugin_name = 'waiting'
    plugin_yaml = '{}-blueprint.yaml'.format(plugin_name)
    plugin_wagon = 'testplugin-0.0.0-py27-none-any.wgn'

    # upload a mock plugin which waits 1 minute, deploy and execute
    tests_root = path.dirname(path.dirname(path.dirname(
        path.realpath(__file__))))
    blueprints_dir = path.join(tests_root, 'resources', 'blueprints', 'mocks')
    cfy.blueprints.upload(path.join(blueprints_dir, plugin_yaml),
                          '-b', plugin_name)
    cfy.plugins.upload(path.join(blueprints_dir, plugin_wagon), '-y',
                       path.join(blueprints_dir, plugin_yaml))
    cfy.deployments.create(plugin_name, '-b', plugin_name)
    _wait_for_deployment_creation(cfy, plugin_name)
    execution_start_time = time.time()
    mgr1.client.executions.start(plugin_name, 'install')

    # check which management worker handles the execution
    exec_node_id = mgr1.client.node_instances.list()[0].id
    time.sleep(3)   # wait for mgmtworker to get the execution
    executing_manager = None
    other_manager = None
    for manager in [mgr1, mgr2]:
        try:
            manager.run_command('grep {} /var/log/cloudify/mgmtworker/'
                                'mgmtworker.log'.format(exec_node_id))
        except Exception:
            continue
        executing_manager = manager
        other_manager = ({mgr1, mgr2} - {executing_manager}).pop()

    # kill the first manager and  wait for execution to finish
    with executing_manager.ssh() as manager_ssh:
        manager_ssh.run('cfy_manager stop')
    manager_failover_time = time.time()
    assert manager_failover_time - execution_start_time < 60
    time.sleep(60)
    other_manager.use(cert_path=other_manager.local_ca)

    # verify on the second manager that the execution completed successfully
    executions = json.loads(cfy.executions.list('--json').stdout)
    installs = [execution for execution in executions
                if execution['workflow_id'] == 'install']
    assert len(installs) == 1
    assert installs[0]['status'] == 'completed'


def _wait_for_deployment_creation(cfy, deployment_id, timeout=15):
    for _ in range(timeout):
        time.sleep(1)
        args = ['--json', '-d', deployment_id]
        deployment_create_execs = json.loads(cfy.executions.list(args).stdout)
        if (len(deployment_create_execs) > 0 and
                deployment_create_execs[0]['status'] == 'completed'):
            return
    raise TimeoutException


def _wait_for_healthy_broker_cluster(cfy, timeout=15):
    for _ in range(timeout):
        time.sleep(2)
        cluster_status = _get_cluster_status(cfy)
        if cluster_status['services']['broker']['status'] == \
                ServiceStatus.HEALTHY:
            return
    raise TimeoutException


def _prepare_cluster_with_agent(managers, logger, module_tmpdir, attributes,
                                ssh_key, cfy):
    logger.info('Installing a deployment with agents')
    hello_world = centos_hello_world(cfy, managers[0], attributes, ssh_key,
                                     logger, module_tmpdir)

    for manager in managers:
        _CloudifyManager.upload_necessary_files(manager)
    _CloudifyManager.upload_plugin(
        managers[0], managers[0]._attributes.default_openstack_plugin)

    # Install a hello world deployment.
    # The test cluster has no outer network access so mgr1.use() won't do, so I
    # use a workaround to run the following functions with the manager's client
    hello_world.upload_blueprint()
    hello_world.create_deployment()
    managers[0].run_command(
        'cfy executions start install -d {deployment_id} -t {tenant} '
        '--timeout 900'.format(deployment_id=hello_world.deployment_id,
                               tenant=hello_world.tenant))
    hello_world.verify_installation()
    return hello_world


def _validate_cluster_and_agents(cfy,
                                 expected_broker_status='OK',
                                 expected_managers_status='OK'):
    validate_agents = cfy.agents.validate()
    assert 'Task succeeded' in validate_agents

    cluster_status = _get_cluster_status(cfy)['services']
    manager_status = _get_manager_status(cfy)
    assert manager_status['status'] == ServiceStatus.HEALTHY
    assert cluster_status['manager']['status'] == expected_managers_status
    assert cluster_status['db']['status'] == ServiceStatus.HEALTHY
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
    db_service = _assert_cluster_status_after_db_changes(
        ServiceStatus.DEGRADED, logger, cfy
    )
    assert db_service['nodes'][db1.hostname]['status'] == ServiceStatus.FAIL

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
    _assert_cluster_status_after_db_changes(ServiceStatus.HEALTHY, logger, cfy)


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
    cluster_status = cfy.cluster.status('--json').stdout
    return json.loads(cluster_status.strip('\033[0m'))


def _get_manager_status(cfy):
    manager_status = cfy.status('--json').stdout
    return json.loads(manager_status.strip('\033[0m'))


@retrying.retry(stop_max_attempt_number=4, wait_fixed=10000)
def _assert_cluster_status_after_db_changes(status, logger, cfy):
    logger.info('Check cluster status after DB changes')
    cluster_status = _get_cluster_status(cfy)
    db_service = cluster_status['services']['db']
    assert cluster_status['status'] == status
    assert db_service['status'] == status
    manager_status = _get_manager_status(cfy)
    assert manager_status['status'] == ServiceStatus.HEALTHY
    logger.info('The cluster status is valid after DB changes')
    return db_service
