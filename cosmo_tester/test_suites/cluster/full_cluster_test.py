import copy
import random
import string
import time
import threading
from os.path import join

import pytest
import retrying

from cloudify.constants import BROKER_PORT_SSL
from cloudify.exceptions import TimeoutException
from cloudify.cluster_status import ServiceStatus, NodeServiceStatus
from cloudify_rest_client.exceptions import CloudifyClientError

from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.test_suites.cluster.conftest import run_cluster_bootstrap
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
    wait_for_restore,
)
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import (get_manager_install_version,
                                         get_resource_path,
                                         set_client_tenant,
                                         wait_for_execution,
                                         delete_deployment,
                                         validate_cluster_status_and_agents)

SNAPSHOTS = 'http://cloudify-tests-files.s3-eu-west-1.amazonaws.com/snapshots/'


def test_full_cluster_ips(full_cluster_ips, logger, ssh_key, test_config):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster_ips

    example = get_example_deployment(mgr1, ssh_key, logger,
                                     'full_cluster_ips',
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


def test_full_cluster_names(full_cluster_names, logger, ssh_key, test_config):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster_names

    example = get_example_deployment(mgr1, ssh_key, logger,
                                     'full_cluster_names',
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


def test_cluster_4_6_0_snapshot_with_idd(full_cluster_ips, logger):
    snapshot_id = 'snap_4.6.0_with_capabilities'
    _test_cluster_snapshot_with_idd(full_cluster_ips, logger, snapshot_id)


def test_cluster_5_0_5_snapshot_with_idd(full_cluster_ips, logger):
    snapshot_id = 'snap_5.0.5_with_capabilities'
    _test_cluster_snapshot_with_idd(full_cluster_ips, logger, snapshot_id)


def _test_cluster_snapshot_with_idd(full_cluster_ips, logger, snapshot_id):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster_ips
    _upload_snapshot_from_resource(mgr1, logger, snapshot_id)
    restore_snapshot(mgr1, snapshot_id, logger)
    wait_for_restore(mgr1, logger)
    _verify_uninstall_idd_guards(mgr1, logger, 'capable', 'infra')


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
    validate_cluster_status_and_agents(mgr1, example.tenant, logger)
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
    validate_cluster_status_and_agents(mgr1, example.tenant, logger,
                                       expected_brokers_status='Degraded')
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

    lb.client._client.cert = lb.local_ca
    lb.wait_for_manager()

    example = get_example_deployment(mgr1, ssh_key, logger,
                                     'manager_failover', test_config)
    example.inputs['server_ip'] = mgr1.ip_address
    example.upload_and_verify_install()
    validate_cluster_status_and_agents(lb, example.tenant, logger,
                                       agent_validation_manager=mgr1)

    # get agent's manager node
    agent_host = lb.client.agents.list(_all_tenants=True)[0]['id']

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

    validate_manager = None
    for manager in [mgr1, mgr2, mgr3]:
        if manager != agent_mgr:
            validate_manager = manager
            break
    assert validate_manager, 'Could not find manager for validation.'

    # stop the manager connected to the agent
    agent_mgr.run_command('cfy_manager stop')

    lb.wait_for_manager()
    time.sleep(5)  # wait 5 secs for status reporter to poll
    validate_cluster_status_and_agents(
        lb, example.tenant, logger, expected_managers_status='Degraded',
        agent_validation_manager=validate_manager)

    # restart the manager connected to the agent
    with agent_mgr.ssh() as manager_ssh:
        manager_ssh.run('cfy_manager start')

    time.sleep(5)
    validate_cluster_status_and_agents(
        lb, example.tenant, logger, agent_validation_manager=validate_manager)

    # stop two managers
    mgr2.run_command('cfy_manager stop')
    mgr3.run_command('cfy_manager stop')

    lb.wait_for_manager()
    time.sleep(5)
    validate_cluster_status_and_agents(lb, example.tenant, logger,
                                       expected_managers_status='Degraded',
                                       agent_validation_manager=mgr1)

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
    # It'll take at least 60 seconds because we told the sleep to be that long
    logger.info('Giving install workflow time to execute (60 seconds)...')
    time.sleep(60)

    # verify on the second manager that the execution completed successfully
    _check_execution_completed(other_manager, example, logger)


# Allow up to 30 seconds in case the platform is being slow
@retrying.retry(stop_max_attempt_number=15, wait_fixed=2000)
def _check_execution_completed(manager, example, logger):
    logger.info('Checking whether install workflow has finished.')
    with set_client_tenant(manager.client, example.tenant):
        executions = manager.client.executions.list()
    installs = [execution for execution in executions
                if execution['workflow_id'] == 'install']
    assert len(installs) == 1
    assert installs[0]['status'] == 'terminated'
    logger.info('Install workflow complete!')


def test_replace_certificates_on_cluster(full_cluster_ips, logger, ssh_key,
                                         test_config, module_tmpdir):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster_ips

    example = get_example_deployment(mgr1, ssh_key, logger,
                                     'cluster_replace_certs', test_config)
    example.inputs['server_ip'] = mgr1.ip_address
    example.upload_and_verify_install()
    validate_cluster_status_and_agents(mgr1, example.tenant, logger)

    for host in broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2:
        key_path = join('~', '.cloudify-test-ca',
                        host.private_ip_address + '.key')
        mgr1.run_command('cfy_manager generate-test-cert'
                         ' -s {0},{1}'.format(host.private_ip_address,
                                              host.ip_address))
        mgr1.run_command('chmod 444 {0}'.format(key_path), use_sudo=True)
    replace_certs_config_path = '~/certificates_replacement_config.yaml'
    _create_replace_certs_config_file(mgr1, replace_certs_config_path,
                                      ssh_key.private_key_path)

    local_new_ca_path = join(str(module_tmpdir), 'new_ca.crt')
    mgr1.get_remote_file('~/.cloudify-test-ca/ca.crt', local_new_ca_path)
    mgr1.client._client.cert = local_new_ca_path

    mgr1.run_command('cfy certificates replace -i {0} -v'.format(
        replace_certs_config_path))

    validate_cluster_status_and_agents(mgr1, example.tenant, logger)
    example.uninstall()


def _create_replace_certs_config_file(manager,
                                      replace_certs_config_path,
                                      local_ssh_key_path):
    remote_script_path = join('/tmp', 'create_replace_certs_config_script.py')
    remote_ssh_key_path = '~/.ssh/ssh_key.pem'

    manager.put_remote_file(remote_ssh_key_path, local_ssh_key_path)
    manager.run_command('cfy profiles set --ssh-user {0} --ssh-key {1}'.format(
        manager.username, remote_ssh_key_path))

    local_script_path = get_resource_path(
        'scripts/create_replace_certs_config_script.py')
    manager.put_remote_file(remote_script_path, local_script_path)
    command = '/opt/cfy/bin/python {0} --output {1} --cluster'.format(
        remote_script_path, replace_certs_config_path)
    manager.run_command(command)


def _wait_for_healthy_broker_cluster(client, timeout=15):
    for _ in range(timeout):
        time.sleep(2)
        cluster_status = client.cluster_status.get_status()
        if cluster_status['services']['broker']['status'] == \
                ServiceStatus.HEALTHY:
            return
    raise TimeoutException


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


def test_full_cluster_status(full_cluster_ips, logger, module_tmpdir):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster_ips

    _assert_cluster_status(mgr1.client)
    _verify_status_when_syncthing_inactive(mgr1, mgr2, logger)
    _verify_status_when_postgres_inactive(db1, db2, logger, mgr1.client)
    _verify_status_when_rabbit_inactive(broker1, broker2, broker3, logger,
                                        mgr1.client)


def test_three_nodes_cluster_status(three_nodes_cluster, logger):
    node1, node2, node3 = three_nodes_cluster
    _assert_cluster_status(node1.client)
    _verify_status_when_syncthing_inactive(node1, node2, logger)
    _verify_status_when_postgres_inactive(node1, node2, logger, node3.client)
    _verify_status_when_rabbit_inactive(node1, node2, node3, logger,
                                        node1.client)


def test_three_nodes_cluster_teardown(three_nodes_cluster, ssh_key,
                                      test_config, module_tmpdir, logger):
    """Tests a cluster teardown"""
    node1, node2, node3 = three_nodes_cluster
    nodes_list = [node1, node2, node3]
    logger.info('Asserting cluster status')
    _assert_cluster_status(node1.client)

    logger.info('Installing example deployment')
    example = get_example_deployment(node1, ssh_key, logger,
                                     'cluster_teardown', test_config)
    example.inputs['server_ip'] = node1.ip_address
    example.upload_and_verify_install()

    logger.info('Removing example deployment')
    example.uninstall()
    logger.info('Removing cluster')
    for node in nodes_list:
        for config_name in ['manager', 'rabbit', 'db']:
            node.run_command('cfy_manager remove -v -c /etc/cloudify/'
                             '{0}_config.yaml'.format(config_name))

    credentials = _get_new_credentials()
    logger.info('New credentials: %s', credentials)

    for node in nodes_list:
        node.install_config = copy.deepcopy(node.basic_install_config)

    logger.info('Installing Cloudify cluster again')
    run_cluster_bootstrap(nodes_list, nodes_list, nodes_list,
                          skip_bootstrap_list=[], pre_cluster_rabbit=True,
                          high_security=True, use_hostnames=False,
                          tempdir=module_tmpdir, test_config=test_config,
                          logger=logger, revert_install_config=True,
                          credentials=credentials)

    logger.info('Asserting cluster status')
    _assert_cluster_status(node1.client)


def test_three_nodes_cluster_upgrade(three_nodes_base_cluster, ssh_key,
                                     test_config, logger):
    nodes_list = [node for node in three_nodes_base_cluster]
    _test_cluster_upgrade(nodes_list, nodes_list[0], 'three', ssh_key,
                          test_config, logger)


def test_nine_nodes_cluster_upgrade(nine_nodes_base_cluster, ssh_key,
                                    test_config, logger):
    nodes_list = [node for node in nine_nodes_base_cluster]
    _test_cluster_upgrade(nodes_list, nodes_list[6], 'nine', ssh_key,
                          test_config, logger)


def _test_cluster_upgrade(nodes_list, manager, prefix, ssh_key, test_config,
                          logger):
    logger.info('Installing example deployment')
    example = get_example_deployment(manager, ssh_key, logger,
                                     '{}_nodes_cluster_upgrade'.format(prefix),
                                     test_config)
    example.inputs['server_ip'] = manager.ip_address
    example.upload_and_verify_install()
    validate_cluster_status_and_agents(manager, example.tenant, logger)

    logger.info('Installing upgrade RPM on nodes')
    _install_upgrade_rpm_on_nodes(nodes_list, test_config, logger)

    if prefix == 'three':
        for config_name in ['db', 'rabbit', 'manager']:
            for i, node in enumerate(nodes_list, start=1):
                logger.info('Upgrading %s %s', config_name, i)
                node.run_command('cfy_manager upgrade -v -c /etc/cloudify/'
                                 '{0}_config.yaml'.format(config_name))
    else:  # prefix == 'nine'
        for node in nodes_list:
            logger.info('Upgrading %s', node.hostname)
            node.run_command('cfy_manager upgrade -v')

    logger.info('Validating nodes upgraded')
    assert_manager_install_version_on_nodes(nodes_list, test_config[
        'upgrade']['upgrade_version'])
    validate_cluster_status_and_agents(manager, example.tenant, logger)

    logger.info('Removing example deployment')
    example.uninstall()


def _install_upgrade_rpm_on_nodes(nodes_list, test_config, logger):
    threads = []
    rpm_path = test_config['upgrade']['upgrade_rpm_path']
    for i, node in enumerate(nodes_list, start=1):
        new_thread = threading.Thread(target=_thread_rpm_upgrade,
                                      args=(node, rpm_path,))
        threads.append(new_thread)
        new_thread.start()
        logger.info('Started installing upgrade RPM on node %s', i)

    for i, thread in enumerate(threads, start=1):
        thread.join()
        logger.info('Finished installing upgrade RPM on node %s', i)


def _thread_rpm_upgrade(node, rpm_path):
    node.run_command('yum install -y {} --disablerepo=*'.format(rpm_path),
                     use_sudo=True, hide_stdout=True)


def assert_manager_install_version_on_nodes(nodes_list, version):
    for node in nodes_list:
        assert get_manager_install_version(node) == version


def _get_new_credentials():
    monitoring_creds = {
        'username': _random_credential_generator(),
        'password': _random_credential_generator()
    }
    postgresql_password = _random_credential_generator()

    return {
        'manager': {  # We're not changing the username and password
            'monitoring': monitoring_creds
        },
        'postgresql_server': {
            'postgres_password': postgresql_password,
            'cluster': {
                'etcd': {
                    'cluster_token': _random_credential_generator(),
                    'root_password': _random_credential_generator(),
                    'patroni_password': _random_credential_generator()
                },
                'patroni': {
                    'rest_password': _random_credential_generator()
                },
                'postgres': {
                    'replicator_password': _random_credential_generator()
                }
            }
        },
        'postgresql_client': {
            'monitoring': monitoring_creds,
            'server_password': postgresql_password
        },
        'rabbitmq': {
            'username': _random_credential_generator(),
            'password': _random_credential_generator(),
            'erlang_cookie': _random_credential_generator(),
            'monitoring': monitoring_creds
        },
        'prometheus': {
            'credentials': monitoring_creds
        }
    }


def _random_credential_generator():
    return ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for _ in range(40))


def _verify_status_when_syncthing_inactive(mgr1, mgr2, logger):
    logger.info('Stopping syncthing on one of the manager nodes')
    mgr1.run_command('supervisorctl stop cloudify-syncthing', use_sudo=True)
    _validate_cluster_status_reporter_syncthing(mgr1, mgr2, logger)


# It can take time for prometheus state to update.
# Thirty seconds should be much more than enough.
@retrying.retry(stop_max_attempt_number=15, wait_fixed=2000)
def _validate_cluster_status_reporter_syncthing(mgr1, mgr2, logger):
    logger.info('Checking status reporter with syncthing down...')

    # Syncthing is down, mgr1 in Fail state
    manager_status = mgr1.client.manager.get_status()
    assert manager_status['status'] == ServiceStatus.FAIL
    assert manager_status['services']['File Sync Service']['status'] == \
        NodeServiceStatus.INACTIVE

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
    mgr1.run_command('supervisorctl start cloudify-syncthing', use_sudo=True)
    _assert_cluster_status(mgr1.client)


def _verify_status_when_postgres_inactive(db1, db2, logger, client):
    logger.info('Stopping one of the db nodes')
    db1.run_command('supervisorctl stop patroni etcd', use_sudo=True)
    db_service = _assert_cluster_status_after_db_changes(
        ServiceStatus.DEGRADED, logger, client,
    )
    assert db_service['nodes'][db1.hostname]['status'] == ServiceStatus.FAIL

    logger.info('Stopping another db node')
    db2.run_command('supervisorctl stop patroni etcd', use_sudo=True)

    try:
        client.cluster_status.get_status()
    except CloudifyClientError:
        logger.info('DB cluster is not healthy, must have minimum 2 nodes')
        pass

    logger.info('Starting Patroni and Etcd on the failed db nodes')
    db1.run_command('supervisorctl start patroni etcd', use_sudo=True)
    db2.run_command('supervisorctl start patroni etcd', use_sudo=True)
    _assert_cluster_status_after_db_changes(ServiceStatus.HEALTHY, logger,
                                            client)


def _verify_status_when_rabbit_inactive(broker1, broker2, broker3, logger,
                                        client):
    logger.info('Stopping one of the rabbit nodes')
    broker1.run_command('supervisorctl stop cloudify-rabbitmq', use_sudo=True)

    _validate_status_when_one_rabbit_inactive(broker1, logger, client)

    logger.info('Stopping the other rabbit nodes')
    broker2.run_command('supervisorctl stop cloudify-rabbitmq', use_sudo=True)
    broker3.run_command('supervisorctl stop cloudify-rabbitmq', use_sudo=True)

    _validate_status_when_all_rabbits_inactive(logger, client)


# It can take time for prometheus state to update.
# Thirty seconds should be much more than enough.
@retrying.retry(stop_max_attempt_number=15, wait_fixed=2000)
def _validate_status_when_one_rabbit_inactive(broker, logger, client):
    logger.info('Checking status reporter with one rabbit down...')
    cluster_status = client.cluster_status.get_status()
    broker_service = cluster_status['services']['broker']
    assert cluster_status['status'] == ServiceStatus.DEGRADED
    assert broker_service['status'] == ServiceStatus.DEGRADED
    assert broker_service['nodes'][broker.hostname]['status'] == \
        ServiceStatus.FAIL
    manager_status = client.manager.get_status()
    assert manager_status['status'] == ServiceStatus.HEALTHY


# It can take time for prometheus state to update.
# Thirty seconds should be much more than enough.
@retrying.retry(stop_max_attempt_number=15, wait_fixed=2000)
def _validate_status_when_all_rabbits_inactive(logger, client):
    logger.info('Checking status reporter with all rabbits down...')
    cluster_status = client.cluster_status.get_status()
    assert cluster_status['status'] == 'Fail'
    assert cluster_status['services']['broker']['status'] == ServiceStatus.FAIL
    manager_status = client.manager.get_status()
    assert manager_status['status'] == 'Fail'


# It can take time for prometheus state to update.
# Thirty seconds should be much more than enough.
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


def _upload_snapshot_from_resource(manager, logger, snapshot_id):
    logger.info('Uploading snapshot: {0}'.format(snapshot_id))
    snapshot_path = get_resource_path('snapshots/{}.zip'.format(snapshot_id))
    manager.client.snapshots.upload(snapshot_path, snapshot_id)


def _verify_uninstall_idd_guards(manager, logger, main_dep_id,
                                 dependent_dep_id):
    deployment_ids = [d.id for d in manager.client.deployments.list()]
    assert {main_dep_id, dependent_dep_id} == set(deployment_ids)

    logger.info('Trying to delete dependent deployment before main. '
                'This should fail.')
    with pytest.raises(CloudifyClientError) as e:
        manager.client.deployments.delete(dependent_dep_id)
    assert "Can't delete deployment {}".format(dependent_dep_id) \
           in str(e.value)
    assert "`{}` uses capabilities".format(main_dep_id) in str(e.value)

    logger.info('Trying to uninstall dependent deployment before main. '
                'This should fail.')
    with pytest.raises(CloudifyClientError) as e:
        manager.client.executions.start(dependent_dep_id, 'uninstall')
    assert "Can't execute workflow `uninstall` on deployment " \
           "{}".format(dependent_dep_id) in str(e.value)
    assert "`{}` uses capabilities".format(main_dep_id) in str(e.value)

    logger.info('Uninstalling and deleting main deployment.')
    execution = manager.client.executions.start(main_dep_id, 'uninstall')
    wait_for_execution(manager.client, execution, logger)
    delete_deployment(manager.client, main_dep_id, logger)

    logger.info('Uninstalling and deleting dependent deployment.')
    execution = manager.client.executions.start(dependent_dep_id, 'uninstall')
    wait_for_execution(manager.client, execution, logger)
    delete_deployment(manager.client, dependent_dep_id, logger)
