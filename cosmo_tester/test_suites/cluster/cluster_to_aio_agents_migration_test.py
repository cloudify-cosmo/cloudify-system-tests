import pytest
from os.path import join

from cosmo_tester.test_suites.agent import validate_agent
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
    wait_for_restore,
    download_snapshot,
    upload_snapshot
)


@pytest.mark.parametrize('three_node_cluster_with_extra_node', ['master'],
                         indirect=['three_node_cluster_with_extra_node'])
def test_migrate_agent_cluster_to_aio(
        three_node_cluster_with_extra_node, module_tmpdir,
        ssh_key, logger, test_config):
    node1, node2, node3, aio_mgr = three_node_cluster_with_extra_node
    aio_mgr.bootstrap()

    logger.info('Installing example deployment on cluster')
    example = get_example_deployment(node1, ssh_key, logger,
                                     'cluster_to_aio_agents', test_config)
    example.inputs['server_ip'] = node1.ip_address
    example.upload_and_verify_install()
    validate_agent(node2, example, test_config)

    logger.info('Creating snapshot on cluster')
    snapshot_id = 'cluster_to_aio_aio_agents'
    snapshot_path = join(str(module_tmpdir), snapshot_id) + '.zip'
    create_snapshot(node3, snapshot_id, logger)
    download_snapshot(node1, snapshot_path, snapshot_id, logger)

    logger.info('Restoring snapshot on AIO manager')
    upload_snapshot(aio_mgr, snapshot_path, snapshot_id, logger)
    restore_snapshot(aio_mgr, snapshot_id, logger, force=True,
                     cert_path=aio_mgr.api_ca_path)
    wait_for_restore(aio_mgr, logger)

    logger.info('Verifying agent connectivity on AIO manager')
    validate_agent(aio_mgr, example, test_config)
    example.uninstall()


@pytest.mark.parametrize('three_node_cluster_with_extra_node', ['master'],
                         indirect=['three_node_cluster_with_extra_node'])
def test_migrate_agent_aio_to_cluster(
        three_node_cluster_with_extra_node, module_tmpdir,
        ssh_key, logger, test_config):
    node1, node2, node3, aio_mgr = three_node_cluster_with_extra_node
    aio_mgr.bootstrap()

    logger.info('Installing example deployment on AIO manager')
    example = get_example_deployment(aio_mgr, ssh_key, logger,
                                     'aio_to_cluster_agents', test_config)
    example.inputs['server_ip'] = aio_mgr.ip_address
    example.upload_and_verify_install()
    validate_agent(aio_mgr, example, test_config)

    logger.info('Creating snapshot on AIO manager')
    snapshot_id = 'cluster_to_aio_aio_agents'
    snapshot_path = join(str(module_tmpdir), snapshot_id) + '.zip'
    create_snapshot(node3, snapshot_id, logger)
    download_snapshot(node3, snapshot_path, snapshot_id, logger)

    logger.info('Restoring snapshot on cluster')
    upload_snapshot(node1, snapshot_path, snapshot_id, logger)
    restore_snapshot(node2, snapshot_id, logger, force=True,
                     cert_path=aio_mgr.api_ca_path)
    wait_for_restore(node2, logger)

    logger.info('Verifying agent connectivity on cluster')
    validate_agent(node3, example, test_config)
    example.uninstall()
