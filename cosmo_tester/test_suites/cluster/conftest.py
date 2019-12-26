import os
import time

import pytest

from cosmo_tester.framework.test_hosts import BootstrappableHosts
from cosmo_tester.framework import util


def skip(*args, **kwargs):
    return True


@pytest.fixture()
def brokers(cfy, ssh_key, module_tmpdir, attributes, logger):
    for _brokers in _get_hosts(cfy, ssh_key, module_tmpdir,
                               attributes, logger, broker_count=3):
        yield _brokers


@pytest.fixture()
def broker(cfy, ssh_key, module_tmpdir, attributes, logger):
    for _brokers in _get_hosts(cfy, ssh_key, module_tmpdir, attributes,
                               logger, broker_count=1):
        yield _brokers[0]


@pytest.fixture()
def dbs(cfy, ssh_key, module_tmpdir, attributes, logger):
    for _dbs in _get_hosts(cfy, ssh_key, module_tmpdir, attributes,
                           logger, db_count=3):
        yield _dbs


@pytest.fixture()
def brokers_and_manager(cfy, ssh_key, module_tmpdir, attributes, logger):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           attributes, logger,
                           broker_count=2, manager_count=1):
        yield _vms


@pytest.fixture()
def brokers3_and_manager(cfy, ssh_key, module_tmpdir, attributes, logger):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           attributes, logger,
                           broker_count=3, manager_count=1):
        yield _vms


@pytest.fixture()
def full_cluster(cfy, ssh_key, module_tmpdir, attributes,
                 logger):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           attributes, logger,
                           broker_count=3, db_count=3, manager_count=2,
                           pre_cluster_rabbit=True):
        yield _vms


@pytest.fixture()
def cluster_missing_one_db(cfy, ssh_key, module_tmpdir, attributes,
                           logger):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           attributes, logger,
                           skip_bootstrap_list=['db3'],
                           broker_count=3, db_count=3, manager_count=2,
                           pre_cluster_rabbit=True):
        yield _vms


@pytest.fixture()
def cluster_with_single_db(cfy, ssh_key, module_tmpdir, attributes,
                           logger):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           attributes, logger,
                           broker_count=3, db_count=1, manager_count=2,
                           pre_cluster_rabbit=True):
        yield _vms


def _get_hosts(cfy, ssh_key, module_tmpdir, attributes, logger,
               broker_count=0, manager_count=0, db_count=0,
               skip_bootstrap_list=None,
               # Pre-cluster rabbit determines whether to cluster rabbit
               # during the bootstrap.
               # High security will pre-set all certs (not just required ones)
               # and use postgres client certs.
               pre_cluster_rabbit=False, high_security=True):
    if skip_bootstrap_list is None:
        skip_bootstrap_list = []
    hosts = BootstrappableHosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=broker_count + db_count + manager_count,
    )

    tempdir = hosts._tmpdir

    try:
        for node in hosts.instances:
            node.verify_services_are_running = skip
            node.upload_necessary_files = skip
            node.upload_plugin = skip

        hosts.create()

        for node in hosts.instances:
            with node.ssh() as fabric_ssh:
                # This needs to happen before we start bootstrapping nodes
                # because the hostname is used by nodes that are being
                # bootstrapped with reference to nodes that may not have been
                # bootstrapped yet.
                node.hostname = str(fabric_ssh.run('hostname -s'))

        brokers = hosts.instances[:broker_count]
        dbs = hosts.instances[broker_count:broker_count + db_count]
        managers = hosts.instances[broker_count + db_count:]

        for node_num, node in enumerate(brokers, start=1):
            _bootstrap_rabbit_node(node, node_num, brokers,
                                   skip_bootstrap_list, pre_cluster_rabbit,
                                   tempdir, logger)

        for node_num, node in enumerate(dbs, start=1):
            _bootstrap_db_node(node, node_num, dbs, skip_bootstrap_list,
                               high_security, tempdir, logger)

        # Ensure all backend nodes are up before installing managers
        for node in brokers + dbs:
            if node.friendly_name in skip_bootstrap_list:
                continue
            while not node.bootstrap_is_complete():
                logger.info('Checking state of {}'.format(node.friendly_name))
                time.sleep(5)

        for node_num, node in enumerate(managers, start=1):
            _bootstrap_manager_node(node, node_num, dbs, brokers,
                                    skip_bootstrap_list, pre_cluster_rabbit,
                                    high_security, tempdir, logger,
                                    attributes)

        logger.info('All nodes are bootstrapped.')

        yield hosts.instances
    finally:
        hosts.destroy()


def _base_prep(node, tempdir):
    with node.ssh() as fabric_ssh:
        fabric_ssh.run(
            'mkdir -p /tmp/bs_logs'
        )

        fabric_ssh.run(
            'echo {name} > /tmp/bs_logs/0_node_name'.format(
                name=node.friendly_name,
            )
        )

    ca_base = os.path.join(tempdir, 'ca.')
    ca_cert = ca_base + 'cert'
    ca_key = ca_base + 'key'

    if not os.path.exists(ca_cert):
        util.generate_ca_cert(ca_cert, ca_key)

    cert_base = os.path.join(tempdir, '{node_friendly_name}.{extension}')

    node_cert = cert_base.format(node_friendly_name=node.friendly_name,
                                 extension='crt')
    node_key = cert_base.format(node_friendly_name=node.friendly_name,
                                extension='key')

    util.generate_ssl_certificate(
        [node.friendly_name, node.hostname,
         node.private_ip_address,
         node.ip_address],
        node.hostname,
        node_cert,
        node_key,
        ca_cert,
        ca_key,
    )

    remote_cert = '/tmp/' + node.friendly_name + '.crt'
    remote_key = '/tmp/' + node.friendly_name + '.key'
    remote_ca = '/tmp/ca.crt'

    node.put_remote_file(
        local_path=node_cert,
        remote_path=remote_cert,
    )
    node.put_remote_file(
        local_path=node_key,
        remote_path=remote_key,
    )
    node.put_remote_file(
        local_path=ca_cert,
        remote_path=remote_ca,
    )

    node.local_cert = node_cert
    node.remote_cert = remote_cert
    node.local_key = node_key
    node.remote_key = remote_key
    node.local_ca = ca_cert
    node.remote_ca = remote_ca


def _bootstrap_rabbit_node(node, rabbit_num, brokers, skip_bootstrap_list,
                           pre_cluster_rabbit, tempdir, logger):
    node.friendly_name = 'rabbit' + str(rabbit_num)

    _base_prep(node, tempdir)

    logger.info('Preparing rabbit {}'.format(node.hostname))

    join_target = ''
    if pre_cluster_rabbit and rabbit_num != 1:
        join_target = brokers[0].hostname

    if pre_cluster_rabbit:
        rabbit_nodes = {
            broker.hostname: {
                'networks': {
                    'default': str(broker.private_ip_address)
                }
            }
            for broker in brokers
        }
    else:
        rabbit_nodes = {}

    node.additional_install_config = {
        'rabbitmq': {
            'ca_path': '/tmp/ca.crt',
            'cert_path': node.remote_cert,
            'key_path': node.remote_key,
            'erlang_cookie': 'thisisacookiefortestingnotproduction',
            'cluster_members': rabbit_nodes,
            'nodename': node.hostname,
            'join_cluster': join_target,
        },
        'services_to_install': ['queue_service'],
    }

    if node.friendly_name in skip_bootstrap_list:
        return

    if pre_cluster_rabbit and rabbit_num == 1:
        node.bootstrap(blocking=True, enter_sanity_mode=False)
    else:
        node.bootstrap(blocking=False, enter_sanity_mode=False)


def _bootstrap_db_node(node, db_num, dbs, skip_bootstrap_list, high_security,
                       tempdir, logger):
    node.friendly_name = 'db' + str(db_num)

    _base_prep(node, tempdir)

    logger.info('Preparing db {}'.format(node.hostname))

    node.pg_password = 'xsqkopcdsog\'je"d<sub;n>osz ,po#qe'

    node.additional_install_config = {
        'postgresql_server': {
            'postgres_password': node.pg_password,
            'cert_path': node.remote_cert,
            'key_path': node.remote_key,
            'ca_path': '/tmp/ca.crt',
        },
        'services_to_install': ['database_service']
    }

    server_conf = node.additional_install_config['postgresql_server']
    if len(dbs) > 1:
        db_nodes = {db.hostname: {'ip': str(db.private_ip_address)}
                    for db in dbs}
        server_conf['cluster'] = {
            'nodes': db_nodes,
            'etcd': {
                'cluster_token': 'jsdiogjdsiogjdiaogjdioagjiodsa',
                'root_password': 'fgiosagjisoagjiosagjiosajgios',
                'patroni_password': 'jgiosagjiosagjsaiogjsio',
            },
            'patroni': {
                'rest_user': 'patroni',
                'rest_password': 'dfsjuiogjisdgjiosdjgiodsjiogsd',
            },
            'postgres': {
                'replicator_password': 'fdsiogjiaohdjkpahsiophe',
            },
        }
    else:
        server_conf['enable_remote_connections'] = True

    if high_security:
        server_conf['ssl_client_verification'] = True
        server_conf['ssl_only_connections'] = True

    if node.friendly_name in skip_bootstrap_list:
        return

    node.bootstrap(blocking=False, enter_sanity_mode=False)


def _bootstrap_manager_node(node, mgr_num, dbs, brokers, skip_bootstrap_list,
                            pre_cluster_rabbit, high_security, tempdir,
                            logger, attributes):
    node.friendly_name = 'manager' + str(mgr_num)

    _base_prep(node, tempdir)

    logger.info('Preparing manager {}'.format(node.hostname))

    if pre_cluster_rabbit:
        rabbit_nodes = {
            broker.hostname: {
                'node_id': broker.get_node_id(),
                'networks': {
                    'default': str(broker.private_ip_address)
                }
            }
            for broker in brokers
        }
    else:
        broker = brokers[0]
        rabbit_nodes = {
            broker.hostname: {
                'networks': {
                    'default': str(broker.private_ip_address)
                }
            }
        }

    node.additional_install_config = {
        'manager': {
            'private_ip': str(node.private_ip_address),
            'public_ip': str(node.private_ip_address),
            'security': {
                'admin_password': attributes.cloudify_password,
            },
        },
        'rabbitmq': {
            'ca_path': '/tmp/ca.crt',
            'cluster_members': rabbit_nodes,
        },
        'services_to_install': ['manager_service'],
    }

    if high_security:
        node.additional_install_config['ssl_inputs'] = {
            'external_cert_path': node.remote_cert,
            'external_key_path': node.remote_key,
            'internal_cert_path': node.remote_cert,
            'internal_key_path': node.remote_key,
            'ca_cert_path': node.remote_ca,
            'external_ca_cert_path': node.remote_ca,
        }
        node.additional_install_config['manager']['security'][
            'ssl_enabled'] = True

    if dbs:
        node.additional_install_config['postgresql_server'] = {
            'ca_path': node.remote_ca,
            'cluster': {'nodes': {}},
        }
        node.additional_install_config['postgresql_client'] = {
            'server_username': 'postgres',
            'server_password': dbs[0].pg_password,
        }

        if len(dbs) > 1:
            db_nodes = {
                db.hostname: {
                    'ip': str(db.private_ip_address),
                    'node_id': db.get_node_id()
                }
                for db in dbs
                if db.friendly_name not in skip_bootstrap_list
            }
            node.additional_install_config['postgresql_server']['cluster'][
                'nodes'] = db_nodes
        else:
            node.additional_install_config['postgresql_client'][
                'host'] = str(dbs[0].private_ip_address)

        if high_security:
            node.additional_install_config['postgresql_client'][
                'ssl_client_verification'] = True
            node.additional_install_config['postgresql_client'][
                'ssl_enabled'] = True
            node.additional_install_config['ssl_inputs'][
                'postgresql_client_cert_path'] = node.remote_cert
            node.additional_install_config['ssl_inputs'][
                'postgresql_client_key_path'] = node.remote_key
    else:
        # If we're installing no db nodes we must put the db on the
        # manager (this only makes sense for testing external rabbit)
        node.additional_install_config[
            'services_to_install'].append('database_service')

    if node.friendly_name in skip_bootstrap_list:
        return

    # We have to block on every manager
    node.bootstrap(blocking=True)

    # Correctly configure the rest client for the node
    node.client = util.create_rest_client(
        str(node.ip_address),
        username=attributes.cloudify_username,
        password=attributes.cloudify_password,
        tenant=attributes.cloudify_tenant,
        api_version=node.api_version,
        cert=node.local_ca,
        protocol='https',
    )
