import pytest
from os.path import join

from cosmo_tester.test_suites.agent import validate_agent
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.snapshots import (
    create_copy_and_restore_snapshot,
)


@pytest.mark.parametrize('three_node_cluster_with_extra_node', ['master'],
                         indirect=['three_node_cluster_with_extra_node'])
def test_migrate_agents_cluster_to_aio(
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

    create_copy_and_restore_snapshot(
        node1, aio_mgr, snapshot_id, snapshot_path, logger,
        cert_path=aio_mgr.api_ca_path)

    logger.info('Migrating to new agents, stopping old agents')
    aio_mgr.run_command(
        'cfy agents install --stop-old-agent --tenant-name {}'.format(
            example.tenant,
        )
    )

    logger.info('Verifying agent connectivity on AIO manager')
    example.manager = aio_mgr
    validate_agent(aio_mgr, example, test_config, upgrade=True)
    example.uninstall()


@pytest.mark.parametrize('three_node_cluster_with_extra_node', ['master'],
                         indirect=['three_node_cluster_with_extra_node'])
def test_migrate_agents_aio_to_cluster(
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

    create_copy_and_restore_snapshot(
        aio_mgr, node1, snapshot_id, snapshot_path, logger,
        cert_path=aio_mgr.api_ca_path)

    logger.info('Migrating to new agents, stopping old agents')
    node1.run_command(
        'cfy agents install --stop-old-agent --tenant-name {}'.format(
            example.tenant,
        )
    )

    logger.info('Verifying agent connectivity on cluster')
    example.manager = node1
    validate_agent(node3, example, test_config, upgrade=True)
    example.uninstall()
