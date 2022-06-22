from os.path import join

import pytest

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import (get_resource_path,
                                         validate_cluster_status_and_agents)


@pytest.mark.nine_vms
def test_replace_certificates_on_cluster(full_cluster_ips, logger, ssh_key,
                                         test_config, replace_ca_key=False):
    broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2, mgr3 = \
        full_cluster_ips

    example = get_example_deployment(mgr1, ssh_key, logger,
                                     'cluster_replace_certs', test_config)
    example.inputs['server_ip'] = mgr1.ip_address
    example.upload_and_verify_install()
    validate_cluster_status_and_agents(mgr1, example.tenant, logger)

    for host in broker1, broker2, broker3, db1, db2, db3, mgr1, mgr2, mgr3:
        key_path = join('~', '.cloudify-test-ca',
                        host.private_ip_address + '.key')
        mgr1.run_command('cfy_manager generate-test-cert'
                         ' -s {0},{1}'.format(host.private_ip_address,
                                              host.ip_address))
        mgr1.run_command('chmod 444 {0}'.format(key_path), use_sudo=True)
    replace_certs_config_path = '~/certificates_replacement_config.yaml'
    _create_replace_certs_config_file(mgr1, replace_certs_config_path,
                                      ssh_key.private_key_path,
                                      replace_ca_key=replace_ca_key)

    mgr1.run_command('cfy certificates replace -i {0} -v'.format(
        replace_certs_config_path))
    mgr1.download_rest_ca(force=True)

    validate_cluster_status_and_agents(mgr1, example.tenant, logger)
    example.uninstall()


@pytest.mark.three_vms
def test_replace_certificates_on_compact_cluster(
        three_nodes_cluster, logger, ssh_key, test_config,
        replace_ca_key=False):
    node1, node2, node3 = three_nodes_cluster

    example = get_example_deployment(node1, ssh_key, logger,
                                     'cluster_replace_certs', test_config)
    example.inputs['server_ip'] = node1.ip_address
    example.upload_and_verify_install()
    validate_cluster_status_and_agents(node1, example.tenant, logger)

    for host in node1, node2, node3:
        key_path = join('~', '.cloudify-test-ca',
                        host.private_ip_address + '.key')
        node1.run_command('cfy_manager generate-test-cert'
                          ' -s {0},{1}'.format(host.private_ip_address,
                                               host.ip_address))
        node1.run_command('chmod 444 {0}'.format(key_path), use_sudo=True)
    replace_certs_config_path = '~/certificates_replacement_config.yaml'
    _create_replace_certs_config_file(node1, replace_certs_config_path,
                                      ssh_key.private_key_path,
                                      replace_ca_key=replace_ca_key)

    node1.run_command('cfy certificates replace -i {0} -v'.format(
        replace_certs_config_path))
    node1.download_rest_ca(force=True)

    validate_cluster_status_and_agents(node1, example.tenant, logger)
    example.uninstall()


@pytest.mark.nine_vms
def test_replace_certificates_on_cluster_incl_ca_key(
        full_cluster_ips, logger, ssh_key, test_config):
    test_replace_certificates_on_cluster(full_cluster_ips, logger, ssh_key,
                                         test_config, replace_ca_key=True)


@pytest.mark.three_vms
def test_replace_certificates_compact_cluster_incl_ca_key(
        three_nodes_cluster, logger, ssh_key, test_config):
    test_replace_certificates_on_compact_cluster(
        three_nodes_cluster, logger, ssh_key, test_config, replace_ca_key=True)


def _create_replace_certs_config_file(manager,
                                      replace_certs_config_path,
                                      local_ssh_key_path,
                                      replace_ca_key=False):
    remote_script_path = join('/tmp', 'create_replace_certs_config_script.py')
    remote_ssh_key_path = '~/.ssh/ssh_key.pem'

    manager.put_remote_file(remote_ssh_key_path, local_ssh_key_path)
    manager.run_command('cfy profiles set --ssh-user {0} --ssh-key {1}'.format(
        manager.username, remote_ssh_key_path))

    local_script_path = get_resource_path(
        'scripts/create_replace_certs_config_script.py')
    manager.put_remote_file(remote_script_path, local_script_path)
    command = '/opt/cfy/bin/python {0} --output {1} --replace-ca-key {2} ' \
              '--cluster'.format(
                remote_script_path, replace_certs_config_path, replace_ca_key)
    manager.run_command(command)
