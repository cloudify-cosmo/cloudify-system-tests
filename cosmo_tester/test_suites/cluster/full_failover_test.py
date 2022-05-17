from math import ceil
import time

import pytest
import retrying

from cloudify.constants import BROKER_PORT_SSL
from cloudify.exceptions import TimeoutException
from cloudify.cluster_status import ServiceStatus

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import (set_client_tenant,
                                         validate_cluster_status_and_agents)


@pytest.mark.six_vms
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
    agent_broker.stop_manager_services()

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
        agent_broker.start_manager_services()
        restarted_broker_ips.append(agent_broker_ip)
        # stop another broker
        for broker in [broker1, broker2, broker3]:
            if broker.private_ip_address == new_agent_broker_ip:
                agent_broker = broker
                break
        _wait_for_healthy_broker_cluster(mgr1.client)
        agent_broker.stop_manager_services()
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


@pytest.mark.six_vms
def test_manager_node_failover(cluster_with_lb, logger, module_tmpdir,
                               ssh_key, test_config):
    broker, db, mgr1, mgr2, mgr3, lb = cluster_with_lb

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
    agent_mgr.stop_manager_services()

    lb.wait_for_manager()
    time.sleep(5)  # wait 5 secs for status reporter to poll
    validate_cluster_status_and_agents(
        lb, example.tenant, logger, expected_managers_status='Degraded',
        agent_validation_manager=validate_manager)

    # restart the manager connected to the agent
    agent_mgr.start_manager_services()

    time.sleep(5)
    validate_cluster_status_and_agents(
        lb, example.tenant, logger, agent_validation_manager=validate_manager)

    # stop two managers
    mgr2.stop_manager_services()
    mgr3.stop_manager_services()

    lb.wait_for_manager()
    time.sleep(5)
    validate_cluster_status_and_agents(lb, example.tenant, logger,
                                       expected_managers_status='Degraded',
                                       agent_validation_manager=mgr1)

    example.uninstall()


@pytest.mark.four_vms
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
            manager.run_command('sudo grep {} /var/log/cloudify/mgmtworker/'
                                'mgmtworker.log'.format(exec_id))
        except Exception:
            continue
        executing_manager = manager
        other_manager = ({mgr1, mgr2} - {executing_manager}).pop()

    # kill the first manager and  wait for execution to finish
    executing_manager.stop_manager_services()
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


def _wait_for_healthy_broker_cluster(client, timeout=60):
    delay = 2.0
    retries = ceil(timeout / delay)
    for _ in range(retries):
        time.sleep(delay)
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
