import copy
import random
import string

import pytest

from cosmo_tester.test_suites.cluster.conftest import run_cluster_bootstrap
from cosmo_tester.framework.examples import get_example_deployment
from .cluster_status_shared import (
    _assert_cluster_status,
    _verify_status_when_postgres_inactive,
    _verify_status_when_rabbit_inactive,
    _verify_status_when_syncthing_inactive,
)


@pytest.mark.three_vms
def test_three_nodes_cluster_status(three_nodes_cluster, logger):
    node1, node2, node3 = three_nodes_cluster
    _assert_cluster_status(node1.client)
    _verify_status_when_syncthing_inactive(node1, node2, logger)
    _verify_status_when_postgres_inactive(node1, node2, logger, node3.client)
    _verify_status_when_rabbit_inactive(node1, node2, node3, logger,
                                        node1.client)


@pytest.mark.three_vms
def test_three_nodes_cluster_teardown(three_nodes_cluster, ssh_key,
                                      test_config, module_tmpdir, logger):
    """Tests a cluster teardown"""
    node1, node2, node3 = three_nodes_cluster
    nodes_list = [node1, node2, node3]
    logger.info('Asserting cluster status')
    _assert_cluster_status(node1.client)

    logger.info('Installing example deployment')
    example = get_example_deployment(node1, ssh_key, logger,
                                     'cluster_teardown', test_config)
    example.inputs['server_ip'] = node1.ip_address
    example.upload_and_verify_install()

    logger.info('Removing example deployment')
    example.uninstall()
    logger.info('Removing cluster')
    for node in nodes_list:
        for config_name in ['manager', 'rabbit', 'db']:
            node.run_command('cfy_manager remove -v -c /etc/cloudify/'
                             '{0}_config.yaml'.format(config_name))

    credentials = _get_new_credentials()
    logger.info('New credentials: %s', credentials)

    for node in nodes_list:
        node.install_config = copy.deepcopy(node.basic_install_config)

    logger.info('Installing Cloudify cluster again')
    run_cluster_bootstrap(nodes_list, nodes_list, nodes_list,
                          skip_bootstrap_list=[], pre_cluster_rabbit=True,
                          high_security=True, use_hostnames=False,
                          tempdir=module_tmpdir, test_config=test_config,
                          logger=logger, revert_install_config=True,
                          credentials=credentials)
    node1.download_rest_ca(force=True)

    logger.info('Asserting cluster status')
    _assert_cluster_status(node1.client)


@pytest.mark.three_vms_ipv6
def test_three_nodes_cluster_ipv6(three_nodes_ipv6_cluster, logger,
                                  ssh_key, test_config):
    node1, node2, node3 = three_nodes_ipv6_cluster
    _assert_cluster_status(node1.client)

    logger.info('Installing example deployment on cluster')
    example = get_example_deployment(node1, ssh_key, logger,
                                     'ipv6_cluster_agent', test_config)
    example.inputs['server_ip'] = node1.private_ip_address
    example.upload_and_verify_install()
    example.uninstall()

    _verify_status_when_syncthing_inactive(node1, node2, logger)
    _verify_status_when_postgres_inactive(node1, node2, logger, node3.client)
    _verify_status_when_rabbit_inactive(node1, node2, node3, logger,
                                        node1.client)


def _get_new_credentials():
    monitoring_creds = {
        'username': _random_credential_generator(),
        'password': _random_credential_generator()
    }
    postgresql_password = _random_credential_generator()

    return {
        'manager': {  # We're not changing the username and password
            'monitoring': monitoring_creds
        },
        'postgresql_server': {
            'postgres_password': postgresql_password,
            'cluster': {
                'etcd': {
                    'cluster_token': _random_credential_generator(),
                    'root_password': _random_credential_generator(),
                    'patroni_password': _random_credential_generator()
                },
                'patroni': {
                    'rest_password': _random_credential_generator()
                },
                'postgres': {
                    'replicator_password': _random_credential_generator()
                }
            }
        },
        'postgresql_client': {
            'monitoring': monitoring_creds,
            'server_password': postgresql_password
        },
        'rabbitmq': {
            'username': _random_credential_generator(),
            'password': _random_credential_generator(),
            'erlang_cookie': _random_credential_generator(),
            'monitoring': monitoring_creds
        },
        'prometheus': {
            'credentials': monitoring_creds
        }
    }


def _random_credential_generator():
    return ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for _ in range(40))
