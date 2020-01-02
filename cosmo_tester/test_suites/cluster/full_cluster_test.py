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


def test_queue_node_failover(cluster_with_single_db, logger, module_tmpdir,
                             attributes, ssh_key, cfy):
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db

    logger.info('Installing a deployment with agents')
    hello_world = centos_hello_world(cfy, mgr1, attributes, ssh_key,
                                     logger, module_tmpdir)

    _CloudifyManager.upload_necessary_files(mgr1)
    _CloudifyManager.upload_plugin(
        mgr1, mgr1._attributes.default_openstack_plugin)
    mgr1.use(cert_path=mgr1.local_ca)
    hello_world.upload_and_verify_install()

    netstat_check_command = \
        'sudo ssh -i /etc/cloudify/key.pem -o StrictHostKeyChecking=no ' \
        'centos@{agent_ip} netstat -na | grep {broker_port}'

    # verify the established connection from host to rabbit mq node
    agent_ip = mgr1.client.agents.list().items[0]['ip']
    agent_netstat_result = mgr1.run_command(netstat_check_command.format(
            agent_ip=agent_ip, broker_port=BROKER_PORT_SSL))
    assert 'ESTABLISHED' in agent_netstat_result
    assert agent_netstat_result.count('tcp') == 1
    agent_broker_ip = agent_netstat_result.split(':')[-2].split(' ')[-1]

    # shutdown the agent's broker node
    for broker in [broker1, broker2, broker3]:
        if broker.private_ip_address == agent_broker_ip:
            with broker.ssh() as broker_ssh:
                broker_ssh.run('sudo service cloudify-rabbitmq stop')
            break

    import pydevd
    pydevd.settrace('192.168.9.43', port=53200, stdoutToServer=True,
                    stderrToServer=True, suspend=True)





    """ TODO:
    use cfy.agents.verify to see if agents are responding.
    se Ahmed's tests in CY-1960
    """


