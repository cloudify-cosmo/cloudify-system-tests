import retrying

from cosmo_tester.test_suites.cluster import check_managers


def test_remove_db_node(full_cluster, logger, cfy):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = full_cluster

    # To aid troubleshooting in case of issues
    _get_db_listing([mgr1])

    # DB management operations are only to be performed in maintenance mode
    mgr1.run_command('cfy maintenance activate')

    # Make sure the node we're about to remove isn't the leader
    db3.run_command(
        # || true in case this node is already the leader
        'cfy_manager dbs set-master -a {} || true'.format(
            db1.private_ip_address,
        )
    )
    db3_node_id = db3.get_node_id()
    db3.run_command('cfy_manager remove --force')

    db1.run_command('cfy_manager dbs remove -a {}'.format(
        db3.private_ip_address,
    ))

    mgr1.run_command('cfy_manager dbs remove -a {0} -i {1}'.format(
        db3.private_ip_address, db3_node_id
    ))
    mgr2.run_command('cfy_manager dbs remove -a {0} -i {1}'.format(
        db3.private_ip_address, db3_node_id
    ))

    _check_db_count(mgr1, mgr2, db3, all_present=False)

    mgr1.run_command('cfy maintenance deactivate')

    check_managers(mgr1, mgr2)


def test_add_db_node(cluster_missing_one_db, logger, cfy):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2 = \
        cluster_missing_one_db

    # To aid troubleshooting in case of issues
    _get_db_listing([mgr1])

    # DB management operations are only to be performed in maintenance mode
    mgr1.run_command('cfy maintenance activate')

    _check_db_count(mgr1, mgr2, db3, all_present=False)

    logger.info('Adding extra DB')
    db3.bootstrap(blocking=True, restservice_expected=False)
    db3_node_id = db3.get_node_id()
    mgr1.run_command('cfy_manager dbs add -a {0} -i {1}'.format(
        db3.private_ip_address, db3_node_id
    ))
    mgr2.run_command('cfy_manager dbs add -a {0} -i {1}'.format(
        db3.private_ip_address, db3_node_id
    ))

    _check_db_count(mgr1, mgr2)

    mgr1.run_command('cfy maintenance deactivate')

    check_managers(mgr1, mgr2)


def test_db_set_master(dbs, logger, cfy):
    db1, db2, db3 = dbs

    for attempt in range(3):
        _wait_for_healthy_db([db1], logger)

        before_change = _get_db_listing([db1])[0]

        next_master = _get_non_leader(before_change)

        try:
            db1.run_command(
                'cfy_manager dbs set-master -a {}'.format(next_master)
            )
            break
        except Exception as err:
            if attempt < 2:
                logger.warning(
                    'Failed to switch DB master. This can happen due to sync '
                    'replica promotion issues, so will be retried. '
                    'Error was: {err}'.format(err=err)
                )
            else:
                raise AssertionError(
                    'Failed to switch DB master with retries. Error was: '
                    '{err}'.format(err=err)
                )

    after_change = _get_db_listing([db1])[0]

    assert after_change != before_change
    _check_cluster(after_change)


def test_db_reinit(dbs, logger, cfy):
    db1, db2, db3 = dbs

    # Ideally we'd test this by damaging a node so that it needed a reinit,
    # but we don't currently have a reliable way to inflict that damage

    listing = _get_db_listing([db1])[0]
    reinit_target = _get_non_leader(listing)

    db1.run_command('cfy_manager dbs reinit -a {}'.format(reinit_target))

    listing = _get_db_listing([db1])[0]
    _check_cluster(listing)


def test_fail_to_remove_db_leader(dbs, logger, cfy):
    db1, db2, db3 = dbs

    listing = _get_db_listing([db1])[0]

    result = db1.run_command(
        'cfy_manager dbs remove -a {} || echo Failed.'.format(
            _get_leader(listing),
        )
    )
    assert 'Failed' in result
    assert 'cannot be removed' in result


def test_fail_to_reinit(dbs, logger, cfy):
    db1, db2, db3 = dbs

    listing = _get_db_listing([db1])[0]

    result = db1.run_command(
        'cfy_manager dbs reinit -a {} || echo Failed.'.format(
            _get_leader(listing),
        )
    )
    assert 'Failed' in result
    assert 'cannot be reinitialised' in result


def _check_cluster(listing, expected_leader=None):
    expected_leader_found = expected_leader is None
    leader_found = False
    sync_replica_found = False
    for entry in listing:
        if entry['state'] == 'leader':
            leader_found = True
            if entry['node_ip'] == expected_leader:
                expected_leader_found = True
        else:
            if entry['state'] == 'sync_replica':
                sync_replica_found = True
    assert expected_leader_found
    assert leader_found
    assert sync_replica_found


def _get_leader(db_listing):
    for entry in db_listing:
        if entry['state'] == 'leader':
            return entry['node_ip']


def _get_non_leader(db_listing):
    for entry in db_listing:
        if entry['state'] != 'leader':
            # It doesn't matter which one we pick, so just get one that is not
            # currently the master
            return entry['node_ip']


def _structure_db_listing(listing):
    # We can do something clever with the actual column headings later if
    # necessary, but that's probably not worth the complexity unless we
    # change the structure much
    structured_nodes = []
    for db_node in listing:
        db_node = db_node.split('|')[1:-1]
        structured_nodes.append({
            'node_ip': db_node[0].strip(),
            'state': db_node[1].strip(),
            'alive': db_node[2].strip(),
            'etcd_state': db_node[3].strip(),
            'errors': db_node[4].strip()
        })
    return structured_nodes


# After db changes the dbs can be out of sync, usually this will be resolved
# within 30 seconds, but we will allow a minute in case of slow test platform
@retrying.retry(stop_max_attempt_number=20, wait_fixed=3000)
def _get_db_listing(nodes):
    # Expected listing output:
    # 2019-10-23 10:43:53,790 - [MAIN] - INFO - DB cluster is healthy.
    # +------------+--------------+-------+---------------+--------+
    # |  node_ip   |    state     | alive |   etcd_state  | errors |
    # +------------+--------------+-------+---------------+--------+
    # |  192.0.2.8 |    leader    |  True |  StateLeader  |        |
    # | 192.0.2.14 | sync_replica |  True | StateFollower |        |
    # +------------+--------------+-------+---------------+--------+
    results = []
    for node in nodes:
        result = [
            line for line in
            node.run_command('cfy_manager dbs list').splitlines()[4:-1]
        ]
        results.append(_structure_db_listing(result))

    return results


# Allow a minute for the cluster to become fully healthy
# (though this will actually allow up to 21 minutes if the underlying
# _get_db_listing hits its max retries every time)
@retrying.retry(stop_max_attempt_number=20, wait_fixed=3000)
def _wait_for_healthy_db(node, logger):
    try:
        _check_cluster(_get_db_listing(node)[0])
    except Exception as err:
        logger.warning(
            'DB not yet healthy: {err}'.format(err=err)
        )
        raise


def _check_db_count(mgr1, mgr2, missing_db=None, all_present=True):
    mgr1_db_results, mgr2_db_results = _get_db_listing([mgr1, mgr2])

    assert mgr1_db_results == mgr2_db_results
    if all_present:
        assert len(mgr1_db_results) == 3
    else:
        assert len(mgr1_db_results) == 2
        # Make sure the old db isn't still present
        for entry in mgr1_db_results:
            assert entry['node_ip'] != str(missing_db.private_ip_address)
