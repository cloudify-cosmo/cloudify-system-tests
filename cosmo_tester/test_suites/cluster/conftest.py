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
                               attributes, logger):
        yield _brokers


@pytest.fixture()
def broker(cfy, ssh_key, module_tmpdir, attributes, logger):
    for _brokers in _get_hosts(cfy, ssh_key, module_tmpdir, attributes,
                               logger, broker_count=1):
        yield _brokers[0]


@pytest.fixture()
def brokers_and_manager(cfy, ssh_key, module_tmpdir, attributes, logger):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           attributes, logger,
                           broker_count=2, manager_count=1):
        yield _vms


@pytest.fixture()
def full_cluster(cfy, ssh_key, module_tmpdir, attributes,
                 logger):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           attributes, logger,
                           broker_count=3, db_count=3, manager_count=2,
                           pre_cluster_rabbit=True):
        yield _vms


def _get_hosts(cfy, ssh_key, module_tmpdir, attributes, logger,
               broker_count=3, manager_count=0, db_count=0,
               # Pre-cluster rabbit determines whether to cluster rabbit
               # during the bootstrap.
               # High security will pre-set all certs (not just required ones)
               # and use postgres client certs.
               pre_cluster_rabbit=False, high_security=True):
    hosts = BootstrappableHosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=broker_count + db_count + manager_count,
    )

    tempdir = hosts._tmpdir

    ca_base = os.path.join(tempdir, 'ca.')
    ca_cert = ca_base + 'cert'
    ca_key = ca_base + 'key'
    util.generate_ca_cert(ca_cert, ca_key)

    cert_base = os.path.join(tempdir, '{node_type}{num}.{extension}')

    try:
        for node in hosts.instances:
            node.verify_services_are_running = skip
            node.upload_necessary_files = skip
            node.upload_plugin = skip
            node.ca_path = ca_cert

        hosts.create()

        for node in hosts.instances:
            with node.ssh() as fabric_ssh:
                node.hostname = str(fabric_ssh.run('hostname -s'))
                fabric_ssh.run(
                    'mkdir -p /tmp/bs_logs'
                )

        brokers = hosts.instances[:broker_count]
        dbs = hosts.instances[broker_count:broker_count + db_count]
        managers = hosts.instances[broker_count + db_count:]

        for node_num, node in enumerate(brokers):
            node.friendly_name = 'rabbit' + str(node_num)
            with node.ssh() as fabric_ssh:
                fabric_ssh.run(
                    'echo {name} > /tmp/bs_logs/0_node_name'.format(
                        name=node.friendly_name,
                    )
                )

            node_cert = cert_base.format(node_type='rabbit', num=node_num,
                                         extension='crt')
            node_key = cert_base.format(node_type='rabbit',
                                        num=node_num, extension='key')

            logger.info('Preparing rabbit {}'.format(node.hostname))
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

            node.put_remote_file(
                local_path=node_cert,
                remote_path='/tmp/rabbit.crt',
            )
            node.put_remote_file(
                local_path=node_key,
                remote_path='/tmp/rabbit.key',
            )
            node.put_remote_file(
                local_path=ca_cert,
                remote_path='/tmp/rabbit.ca',
            )

            join_target = ''
            if pre_cluster_rabbit and node_num != 0:
                join_target = brokers[0].hostname

            if pre_cluster_rabbit:
                print(dir(brokers[0]))
                rabbit_nodes = {
                    broker.hostname: {
                        'default': str(broker.private_ip_address),
                    }
                    for broker in brokers
                }
            else:
                rabbit_nodes = {}

            node.additional_install_config = {
                'rabbitmq': {
                    'ca_path': '/tmp/rabbit.ca',
                    'cert_path': '/tmp/rabbit.crt',
                    'key_path': '/tmp/rabbit.key',
                    'erlang_cookie': 'thisisacookiefortestingnotproduction',
                    'cluster_members': rabbit_nodes,
                    'nodename': node.hostname,
                    'join_cluster': join_target,
                },
                'services_to_install': ['queue_service'],
            }

            if pre_cluster_rabbit and node_num == 0:
                node.bootstrap(blocking=True, enter_sanity_mode=False)
            else:
                node.bootstrap(blocking=False, enter_sanity_mode=False)

        for node_num, node in enumerate(dbs):
            node.friendly_name = 'db' + str(node_num)
            with node.ssh() as fabric_ssh:
                fabric_ssh.run(
                    'echo {name} > /tmp/bs_logs/0_node_name'.format(
                        name=node.friendly_name,
                    )
                )

            node_cert = cert_base.format(node_type='db', num=node_num,
                                         extension='crt')
            node_key = cert_base.format(node_type='db',
                                        num=node_num, extension='key')

            logger.info('Preparing db {}'.format(node.hostname))
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

            node.put_remote_file(
                local_path=node_cert,
                remote_path='/tmp/db.crt',
            )
            node.put_remote_file(
                local_path=node_key,
                remote_path='/tmp/db.key',
            )
            node.put_remote_file(
                local_path=ca_cert,
                remote_path='/tmp/db.ca',
            )

            node.pg_password = 'xsqkopcdsogjedsubnosz ,poqe'

            node.additional_install_config = {
                'postgresql_server': {
                    'postgres_password': node.pg_password,
                    'cert_path': '/tmp/db.crt',
                    'key_path': '/tmp/db.key',
                    'ca_path': '/tmp/db.ca',
                    'cluster': {
                        'nodes': [str(db.private_ip_address) for db in dbs],
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
                },
                'services_to_install': ['database_service']
            }
            if high_security:
                node.additional_install_config['postgresql_server'][
                    'ssl_client_verification'] = True
                node.additional_install_config['postgresql_server'][
                    'ssl_only_connections'] = True

            node.bootstrap(blocking=False, enter_sanity_mode=False)

        # Ensure all backend nodes are up before installing managers
        for node in brokers + dbs:
            while not node.bootstrap_is_complete():
                logger.info('Checking state of {}'.format(node.friendly_name))
                time.sleep(5)

        for node_num, node in enumerate(managers):
            logger.info('Preparing manager {}'.format(node.hostname))
            node.friendly_name = 'manager' + str(node_num)
            with node.ssh() as fabric_ssh:
                fabric_ssh.run(
                    'echo {name} > /tmp/bs_logs/0_node_name'.format(
                        name=node.friendly_name,
                    )
                )

            node.put_remote_file(
                local_path=ca_cert,
                remote_path='/tmp/cluster.ca',
            )

            if pre_cluster_rabbit:
                rabbit_nodes = {
                    broker.hostname: {
                        'default': str(broker.private_ip_address),
                    }
                    for broker in brokers
                }
            else:
                broker = brokers[0]
                rabbit_nodes = {
                    broker.hostname: {
                        'default': str(broker.private_ip_address),
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
                    'ca_path': '/tmp/cluster.ca',
                    'cluster_members': rabbit_nodes,
                },
                'services_to_install': ['manager_service'],
            }

            if high_security:
                node_cert = cert_base.format(node_type='manager',
                                             num=node_num,
                                             extension='crt')
                node_key = cert_base.format(node_type='manager',
                                            num=node_num, extension='key')

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

                node.put_remote_file(
                    local_path=node_cert,
                    remote_path='/tmp/node.crt',
                )
                node.put_remote_file(
                    local_path=node_key,
                    remote_path='/tmp/node.key',
                )
                node.additional_install_config['ssl_inputs'] = {
                    'external_cert_path': '/tmp/node.crt',
                    'external_key_path': '/tmp/node.key',
                    'internal_cert_path': '/tmp/node.crt',
                    'internal_key_path': '/tmp/node.key',
                    'ca_cert_path': '/tmp/cluster.ca',
                    'external_ca_cert_path': '/tmp/cluster.ca',
                }
                node.additional_install_config['manager']['security'][
                    'ssl_enabled'] = True

            if len(dbs) > 1:
                node.additional_install_config['postgresql_server'] = {
                    'ca_path': '/tmp/cluster.ca',
                    'cluster': {
                        'nodes': [str(db.private_ip_address) for db in dbs],
                    },
                }
                node.additional_install_config['postgresql_client'] = {
                    'server_username': 'postgres',
                    'server_password': dbs[0].pg_password,
                }
                if high_security:
                    node.additional_install_config['postgresql_client'][
                        'ssl_client_verification'] = True
                    node.additional_install_config['postgresql_client'][
                        'ssl_enabled'] = True
                    node.additional_install_config['ssl_inputs'][
                        'postgresql_client_cert_path'] = '/tmp/node.crt'
                    node.additional_install_config['ssl_inputs'][
                        'postgresql_client_key_path'] = '/tmp/node.key'
            elif len(dbs) == 1:
                raise NotImplemented(
                    'Cluster tests do not currently support a single DB'
                )
            else:
                # If we're installing no db nodes we must put the db on the
                # manager (this only makes sense for testing external rabbit)
                node.additional_install_config[
                    'services_to_install'].append('database_service')

            # We have to block on every manager
            node.bootstrap(blocking=True)

            # Correctly configure the rest client for the node
            node.client = util.create_rest_client(
                str(node.ip_address),
                username=attributes.cloudify_username,
                password=attributes.cloudify_password,
                tenant=attributes.cloudify_tenant,
                api_version=node.api_version,
                cert=ca_cert,
                protocol='https',
            )

        logger.info('All nodes are bootstrapped.')

        yield hosts.instances
    finally:
        hosts.destroy()
