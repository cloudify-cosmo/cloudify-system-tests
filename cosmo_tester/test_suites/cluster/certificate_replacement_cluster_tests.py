from os.path import join

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import (get_resource_path,
                                         validate_cluster_status_and_agents)


def test_replace_certificates_on_cluster(full_cluster_ips, logger, ssh_key,
                                         test_config, module_tmpdir):
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
                                      ssh_key.private_key_path)

    local_new_ca_path = join(str(module_tmpdir), 'new_ca.crt')
    mgr1.get_remote_file('~/.cloudify-test-ca/ca.crt', local_new_ca_path)
    mgr1.client._client.cert = local_new_ca_path

    mgr1.run_command('cfy certificates replace -i {0} -v'.format(
        replace_certs_config_path))

    validate_cluster_status_and_agents(mgr1, example.tenant, logger)
    example.uninstall()


def _create_replace_certs_config_file(manager,
                                      replace_certs_config_path,
                                      local_ssh_key_path):
    remote_script_path = join('/tmp', 'create_replace_certs_config_script.py')
    remote_ssh_key_path = '~/.ssh/ssh_key.pem'

    manager.put_remote_file(remote_ssh_key_path, local_ssh_key_path)
    manager.run_command('cfy profiles set --ssh-user {0} --ssh-key {1}'.format(
        manager.username, remote_ssh_key_path))

    local_script_path = get_resource_path(
        'scripts/create_replace_certs_config_script.py')
    manager.put_remote_file(remote_script_path, local_script_path)
    command = '/opt/cfy/bin/python {0} --output {1} --cluster'.format(
        remote_script_path, replace_certs_config_path)
    manager.run_command(command)
