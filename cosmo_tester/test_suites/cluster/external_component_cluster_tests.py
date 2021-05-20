from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)


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
                     cert_path=mgr2.api_ca_path)

    check_managers(mgr1, mgr2, example)
