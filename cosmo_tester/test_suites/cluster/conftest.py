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
def brokers_and_dbs_and_managers(cfy, ssh_key, module_tmpdir, attributes,
                                 logger):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           attributes, logger,
                           broker_count=3, db_count=3, manager_count=2):
        yield _vms


def _get_hosts(cfy, ssh_key, module_tmpdir, attributes, logger,
               broker_count=3, manager_count=0, db_count=0,
               pre_cluster_rabbit=False):
    hosts = BootstrappableHosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=broker_count + manager_count,
    )

    tempdir = hosts._tmpdir

    ca_base = os.path.join(tempdir, 'ca.')
    ca_cert = ca_base + 'cert'
    ca_key = ca_base + 'key'
    util.generate_ca_cert(ca_cert, ca_key)

    cert_base = os.path.join(tempdir, 'node{num}.{extension}')

    try:
        for node in hosts.instances:
            node.verify_services_are_running = skip
            node.upload_necessary_files = skip
            node.upload_plugin = skip

        hosts.create()

        brokers = hosts.instances[:broker_count]
        dbs = hosts.instances[broker_count:broker_count + db_count]
        managers = hosts.instances[broker_count + db_count:]

        for node_num, node in enumerate(brokers):
            node_cert = cert_base.format(num=node_num, extension='crt')
            node_key = cert_base.format(num=node_num, extension='key')

            with node.ssh() as fabric_ssh:
                node.hostname = str(fabric_ssh.run('hostname -s'))
                logger.info('Preparing {}'.format(node.hostname))
            util.generate_ssl_certificate(
                [node.hostname, node.private_ip_address],
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

            node.additional_install_config = {
                'rabbitmq': {
                    'ca_path': '/tmp/rabbit.ca',
                    'cert_path': '/tmp/rabbit.crt',
                    'key_path': '/tmp/rabbit.key',
                    'erlang_cookie': 'thisisacookiefortestingnotproduction',
                    'nodename': node.hostname,
                    'join_cluster': join_target,
                },
                'services_to_install': ['queue_service'],
            }
            if pre_cluster_rabbit and node_num == 0:
                node.bootstrap(blocking=True)
            else:
                node.bootstrap(blocking=False)

        for node_num, node in enumerate(dbs):
            # TODO
            pass

        for node in brokers + dbs:
            while not node.bootstrap_is_complete():
                time.sleep(5)

        for node_num, node in enumerate(managers):
            with node.ssh() as fabric_ssh:
                node.hostname = str(fabric_ssh.run('hostname -s'))
                logger.info('Preparing {}'.format(node.hostname))

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
                'rabbitmq': {
                    'ca_path': '/tmp/cluster.ca',
                    'cluster_members': rabbit_nodes,
                },
                'services_to_install': ['manager_service'],
            }

            if len(dbs) == 0:
                node.additional_install_config[
                    'services_to_install'].append('database_service')
                # TODO: Add db config

            # We have to block on every manager
            node.bootstrap(blocking=True)

        logger.info('All nodes are bootstrapped.')

        yield hosts.instances
    finally:
        hosts.destroy()
