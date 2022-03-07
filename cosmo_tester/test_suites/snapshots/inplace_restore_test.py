from time import sleep
from os.path import join

import pytest

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.test_hosts import Hosts, VM
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    download_snapshot,
    restore_snapshot,
    upload_snapshot,
)


@pytest.fixture(scope='function')
def manager_and_vm(request, ssh_key, module_tmpdir, test_config,
                   logger):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request, 2)
    hosts.instances[0] = VM('master', test_config)
    hosts.instances[1] = VM('centos_7', test_config)
    manager, vm = hosts.instances

    passed = True

    try:
        hosts.create()
        yield hosts.instances
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)


@pytest.fixture(scope='function')
def example(manager_and_vm, ssh_key, tmpdir, logger, test_config):
    manager, vm = manager_and_vm

    example = get_example_deployment(
        manager, ssh_key, logger, 'inplace_restore', test_config, vm)

    try:
        yield example
    finally:
        if example.installed:
            example.uninstall()


def test_inplace_restore(manager_and_vm,
                         example,
                         module_tmpdir,
                         logger):
    manager, vm = manager_and_vm

    snapshot_name = 'inplace_restore_snapshot_{0}'.format(manager.image_type)
    snapshot_path = join(str(module_tmpdir), snapshot_name) + '.zip'

    example.upload_and_verify_install()

    create_snapshot(manager, snapshot_name, logger)
    download_snapshot(manager, snapshot_path, snapshot_name, logger)
    # We need the certs to be the same for the 'new' manager otherwise an
    # inplace upgrade can't properly work
    manager.run_command('mkdir /tmp/ssl_backup')
    manager.run_command('cp /etc/cloudify/ssl/* /tmp/ssl_backup',
                        use_sudo=True)
    manager.teardown()
    # The teardown doesn't properly clean up rabbitmq
    manager.run_command('pkill -f rabbitmq', use_sudo=True)
    manager.run_command('rm -rf /var/lib/rabbitmq', use_sudo=True)
    manager.install_config['rabbitmq'] = {
        'ca_path': '/tmp/ssl_backup/cloudify_internal_ca_cert.pem',
        'cert_path': '/tmp/ssl_backup/rabbitmq-cert.pem',
        'key_path': '/tmp/ssl_backup/rabbitmq-key.pem',
    }
    manager.install_config['prometheus'] = {
        'ca_path': '/tmp/ssl_backup/cloudify_internal_ca_cert.pem',
        'cert_path': '/tmp/ssl_backup/monitoring_cert.pem',
        'key_path': '/tmp/ssl_backup/monitoring_key.pem',
    }
    manager.install_config['ssl_inputs'] = {
        'external_cert_path': '/tmp/ssl_backup/cloudify_external_cert.pem',
        'external_key_path': '/tmp/ssl_backup/cloudify_external_key.pem',
        'internal_cert_path': '/tmp/ssl_backup/cloudify_internal_cert.pem',
        'internal_key_path': '/tmp/ssl_backup/cloudify_internal_key.pem',
        'ca_cert_path': '/tmp/ssl_backup/cloudify_internal_ca_cert.pem',
        'external_ca_cert_path':
            '/tmp/ssl_backup/cloudify_internal_ca_cert.pem',
    }
    manager.bootstrap()
    upload_snapshot(manager, snapshot_path, snapshot_name, logger)

    restore_snapshot(manager, snapshot_name, logger,
                     admin_password=manager.mgr_password)
    manager.wait_for_manager()

    logger.info('Waiting 35 seconds for agents to reconnect. '
                'Agent reconnect retries are up to 30 seconds apart.')
    sleep(35)

    example.uninstall()
