from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)


def test_full_cluster(full_cluster, logger, attributes, cfy):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster

    logger.info('Creating snapshot')
    snapshot_id = 'cluster_test_snapshot'
    create_snapshot(mgr1, snapshot_id, attributes, logger)

    logger.info('Restoring snapshot')
    restore_snapshot(mgr2, snapshot_id, cfy, logger, force=True,
                     cert_path=mgr2.ca_path)

    # Run sanity checks on each manager independently to confirm they can
    # independently run workflows
    mgr2.run_command('sudo systemctl stop cloudify-mgmtworker')
    mgr1.run_command('cfy_manager sanity-check')
    mgr2.run_command('sudo systemctl start cloudify-mgmtworker')
    mgr1.run_command('sudo systemctl stop cloudify-mgmtworker')
    mgr2.run_command('cfy_manager sanity-check')
    mgr1.run_command('sudo systemctl start cloudify-mgmtworker')
