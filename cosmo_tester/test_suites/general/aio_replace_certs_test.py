from os.path import join

import pytest

from cosmo_tester.framework.util import validate_agents
from cosmo_tester.framework.util import get_resource_path
from cosmo_tester.framework.examples import get_example_deployment


@pytest.mark.cert_replace
def test_aio_replace_certs(image_based_manager, ssh_key, logger, test_config,
                           replace_ca_key=False):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, 'aio_replace_certs', test_config)
    example.upload_and_verify_install()
    validate_agents(image_based_manager, example.tenant)

    _create_new_certs(image_based_manager)
    replace_certs_config_path = '~/certificates_replacement_config.yaml'
    _create_replace_certs_config_file(image_based_manager,
                                      replace_certs_config_path,
                                      ssh_key.private_key_path,
                                      replace_ca_key=replace_ca_key)

    image_based_manager.run_command('cfy certificates replace -i {0} '
                                    '-v'.format(replace_certs_config_path))
    image_based_manager.download_rest_ca(force=True)

    validate_agents(image_based_manager, example.tenant)
    example.uninstall()


@pytest.mark.cert_replace
def test_aio_replace_certs_incl_ca_key(
        image_based_manager, ssh_key, logger, test_config):
    test_aio_replace_certs(image_based_manager, ssh_key, logger, test_config,
                           replace_ca_key=True)


def _create_new_certs(manager):
    key_path = join('~', '.cloudify-test-ca',
                    manager.private_ip_address + '.key')
    manager.run_command('cfy_manager generate-test-cert -s {0},{1}'.format(
        manager.private_ip_address, manager.ip_address))
    manager.run_command('chmod 444 {0}'.format(key_path), use_sudo=True)


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
    command = '/opt/cfy/bin/python {0} --output {1} --host-ip {2} ' \
              '--replace-ca-key {3}'.format(
                remote_script_path, replace_certs_config_path,
                manager.private_ip_address, replace_ca_key)
    manager.run_command(command)
