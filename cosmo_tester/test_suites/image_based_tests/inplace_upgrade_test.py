from time import sleep
from os.path import join

import pytest

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.test_hosts import (
    Hosts,
    get_image,
)
from cosmo_tester.snapshots import (
    create_snapshot,
    download_snapshot,
    restore_snapshot,
    upload_snapshot,
)


@pytest.fixture(scope='module', params=['5.0.5', 'master'])
def manager_and_vm(request, ssh_key, module_tmpdir, test_config,
                   logger):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request, 2)
    hosts.instances[0] = get_image(request.param, test_config)
    manager, vm = hosts.instances

    manager.restservice_expected = True

    vm.image_name = test_config.platform['centos_7_image']
    vm.username = test_config['test_os_usernames']['centos_7']

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
        manager, ssh_key, logger, 'inplace_upgrade', test_config, vm)

    try:
        yield example
    finally:
        if example.installed:
            example.uninstall()


def test_inplace_upgrade(manager_and_vm,
                         example,
                         ssh_key,
                         module_tmpdir,
                         logger):
    manager, vm = manager_and_vm

    snapshot_name = 'inplace_upgrade_snapshot_{0}'.format(manager.image_type)
    snapshot_path = join(str(module_tmpdir), snapshot_name) + '.zip'

    example.upload_and_verify_install()

    create_snapshot(manager, snapshot_name, logger)
    download_snapshot(manager, snapshot_path, snapshot_name, logger)
    manager.teardown()
    with manager.ssh() as fabric_ssh:
        # The teardown doesn't properly clean up rabbitmq
        fabric_ssh.sudo('pkill -f rabbitmq')
        fabric_ssh.sudo('rm -rf /var/lib/rabbitmq')
    manager.bootstrap()
    upload_snapshot(manager, snapshot_path, snapshot_name, logger)

    with manager.ssh() as fabric_ssh:
        # Perform the restore after opening the ssh session and don't wait for
        # the execution to finish to avoid a race condition that occasionally
        # causes test failures when we don't ssh in before the shutdown.
        restore_snapshot(manager, snapshot_name, logger,
                         restore_certificates=True, blocking=False)
        retry_delay = 1
        max_attempts = 240
        reboot_triggered = False
        reboot_performed = False
        for attempt in range(0, max_attempts):
            try:
                if fabric_ssh.run(
                    'ps aux | grep shutdown | grep -v grep || true'
                ).stdout.strip():
                    # Still waiting for post-restore reboot
                    sleep(retry_delay)
                    reboot_triggered = True
                    logger.info('Reboot trigger has been set.')
                    continue
                elif reboot_triggered:
                    reboot_performed = True
                    logger.info('Reboot has been performed, continuing.')
                    break
                else:
                    sleep(retry_delay)
            except Exception:
                if attempt == max_attempts - 1:
                    raise
                sleep(retry_delay)
        if not reboot_triggered:
            log_tail = fabric_ssh.run(
                'sudo tail -n30 '
                '/var/log/cloudify/mgmtworker/logs/__system__.log'
            ).stdout.strip()
            raise RuntimeError(
                'Did not see reboot trigger. '
                'Did the manager already reboot?\n'
                'End of snapshot log:\n'
                '{log_tail}'.format(log_tail=log_tail)
            )
        if not reboot_performed:
            raise RuntimeError('Expected reboot did not happen.')

    # we need to give the agents enough time to reconnect to the manager;
    # celery retries with a backoff of up to 32 seconds
    sleep(50)
    manager.wait_for_manager()

    example.uninstall()
