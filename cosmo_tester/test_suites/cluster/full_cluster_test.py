import pytest

from cloudify_rest_client.exceptions import CloudifyClientError

from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
    wait_for_restore,
)
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import (get_resource_path,
                                         wait_for_execution,
                                         delete_deployment)
from .cluster_status_shared import (
    _assert_cluster_status,
    _verify_status_when_postgres_inactive,
    _verify_status_when_rabbit_inactive,
    _verify_status_when_syncthing_inactive,
)


@pytest.mark.nine_vms
def test_full_cluster_ips(full_cluster_ips, logger, ssh_key, test_config):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2, mgr3 = \
        full_cluster_ips

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
                     cert_path=mgr2.api_ca_path)

    check_managers(mgr1, mgr2, example)


@pytest.mark.nine_vms
def test_full_cluster_names(full_cluster_names, logger, ssh_key, test_config):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2, mgr3 = \
        full_cluster_names

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
                     cert_path=mgr2.api_ca_path)

    check_managers(mgr1, mgr2, example)


@pytest.mark.nine_vms
def test_cluster_5_0_5_snapshot_with_idd(full_cluster_ips, logger):
    snapshot_id = 'snap_5.0.5_with_capabilities'
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2, mgr3 = \
        full_cluster_ips
    _upload_snapshot_from_resource(mgr1, logger, snapshot_id)
    restore_snapshot(mgr1, snapshot_id, logger)
    wait_for_restore(mgr1, logger)
    _verify_uninstall_idd_guards(mgr1, logger, 'capable', 'infra')


@pytest.mark.nine_vms
def test_full_cluster_status(full_cluster_ips, logger, module_tmpdir):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2, mgr3 = \
        full_cluster_ips

    _assert_cluster_status(mgr1.client)
    _verify_status_when_syncthing_inactive(mgr1, mgr2, logger)
    _verify_status_when_postgres_inactive(db1, db2, logger, mgr1.client)
    _verify_status_when_rabbit_inactive(broker1, broker2, broker3, logger,
                                        mgr1.client)


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
