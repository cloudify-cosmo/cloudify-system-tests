from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)
from cosmo_tester.framework.examples.hello_world import centos_hello_world
from cosmo_tester.framework.test_hosts import _CloudifyManager

# for openstack plugin
OS_WGN_FILENAME_TEMPLATE = 'cloudify_openstack_plugin-{0}-py27-none-linux_x86_64-redhat-Maipo.wgn'  # NOQA
OS_YAML_URL_TEMPLATE = 'https://raw.githubusercontent.com/cloudify-cosmo/cloudify-openstack-plugin/{0}/plugin.yaml'  # NOQA
OS_WGN_URL_TEMPLATE = 'http://repository.cloudifysource.org/cloudify/wagons/cloudify-openstack-plugin/{0}/{1}'  # NOQA
OS_PLUGIN_VERSION = '2.14.7'
OS_PLUGIN_WGN_FILENAME = OS_WGN_FILENAME_TEMPLATE.format(OS_PLUGIN_VERSION)
OS_PLUGIN_WGN_URL = OS_WGN_URL_TEMPLATE.format(OS_PLUGIN_VERSION,
                                               OS_PLUGIN_WGN_FILENAME)
OS_PLUGIN_YAML_URL = OS_YAML_URL_TEMPLATE.format(OS_PLUGIN_VERSION)


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
    mgr1.use(cert_path=mgr1.local_ca)
    mgr1.run_command('cfy plugins upload {0} -y {1}'.format(
        OS_PLUGIN_WGN_URL, OS_PLUGIN_YAML_URL))

    """ TODO: 
    wait for plugin to finish installing, so that the plugin won't 
    be in a 'corrupt state'
    """

    hello_world.upload_and_verify_install()

    import pydevd
    pydevd.settrace('192.168.9.43', port=53200, stdoutToServer=True,
                    stderrToServer=True, suspend=True)
    kill_node(broker1)

    """ TODO:
    use cfy.agents.verify to see if agents are responding.
    se Ahmed's tests in CY-1960
    """


def kill_node(broker):
    with broker.ssh() as broker_ssh:
        broker_ssh.run('sudo service cloudify-rabbitmq stop')
        broker_ssh.run('sudo shutdown -h now &')
