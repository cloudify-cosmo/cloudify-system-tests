import retrying

from cloudify.cluster_status import ServiceStatus, NodeServiceStatus
from cloudify_rest_client.exceptions import CloudifyClientError


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


# It's always fun having a status checker that caches things, let's retry in
# more places!
@retrying.retry(stop_max_attempt_number=4, wait_fixed=5000)
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
        logger.info('DB cluster is correctly not healthy with 2 nodes gone')

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
