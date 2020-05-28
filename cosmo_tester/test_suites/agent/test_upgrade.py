import pytest

from cosmo_tester.framework import util
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.test_hosts import Hosts

from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    download_snapshot,
    restore_snapshot,
    upload_snapshot,
)


@pytest.fixture(scope='module')
def managers_and_vm(ssh_key, module_tmpdir, test_config, logger,
                    request):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request,
                  3)

    passed = True

    try:
        managers = hosts.instances[:2]
        vm = hosts.instances[2]

        managers[0].restservice_expected = True
        managers[1].restservice_expected = True

        vm.image_name = test_config.platform['centos_7_image']
        vm.username = test_config['test_os_usernames']['centos_7']

        hosts.create()
        yield hosts.instances
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)


@pytest.fixture(scope='function')
def example(managers_and_vm, ssh_key, tmpdir, logger, test_config):
    manager = managers_and_vm[0]
    vm = managers_and_vm[2]

    example = get_example_deployment(manager, ssh_key, logger,
                                     'agent_upgrade', test_config, vm)

    try:
        yield example
    finally:
        if example.installed:
            example.uninstall()


def test_old_agent_stopped_after_agent_upgrade(
        managers_and_vm, example, logger, tmpdir
):
    local_snapshot_path = str(tmpdir / 'snapshot.zip')
    snapshot_id = 'snap'

    old_manager, new_manager, vm = managers_and_vm

    example.upload_and_verify_install()

    create_snapshot(old_manager, snapshot_id, logger)
    old_manager.wait_for_all_executions()
    download_snapshot(old_manager, local_snapshot_path, snapshot_id, logger)

    upload_snapshot(new_manager, local_snapshot_path, snapshot_id, logger)
    restore_snapshot(new_manager, snapshot_id, logger)

    # Before upgrading the agents, the old agent should still be up
    old_manager.run_command('cfy agents validate --tenant-name {}'.format(
        example.tenant,
    ))

    # Upgrade to new agents and stop old agents
    new_manager.run_command(
        'cfy agents install --stop-old-agent --tenant-name {}'.format(
            example.tenant,
        )
    )

    logger.info('Validating the old agent is indeed down')
    _assert_agent_not_running(old_manager, vm, 'vm', example.tenant)
    old_manager.stop()

    example.manager = new_manager
    example.check_files()
    example.uninstall()


def _assert_agent_not_running(manager, vm, node_name, tenant):
    with util.set_client_tenant(manager.client, tenant):
        node = manager.client.node_instances.list(node_id=node_name)[0]
    agent = node.runtime_properties['cloudify_agent']
    ssh_command = 'sudo service cloudify-worker-{name} status'.format(
        name=agent['name'],
    )
    response = vm.run_command(ssh_command, warn_only=True).stdout
    assert 'inactive' in response
