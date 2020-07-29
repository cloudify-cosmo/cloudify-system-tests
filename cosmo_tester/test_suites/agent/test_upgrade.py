from cosmo_tester.framework import util
from cosmo_tester.framework.examples import get_example_deployment

from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    download_snapshot,
    restore_snapshot,
    upload_snapshot,
)

from cosmo_tester.test_suites.agent import get_test_prerequisites


def test_old_agent_stopped_after_upgrade_windows(ssh_key, module_tmpdir,
                                                 test_config, logger, tmpdir,
                                                 request):
    _test_old_agent_stopped_after_agent_upgrade(ssh_key, module_tmpdir,
                                                test_config, logger, tmpdir,
                                                request, 'windows_2012')


def test_old_agent_stopped_after_upgrade_linux(ssh_key, module_tmpdir,
                                               test_config, logger, tmpdir,
                                               request):
    _test_old_agent_stopped_after_agent_upgrade(ssh_key, module_tmpdir,
                                                test_config, logger, tmpdir,
                                                request, 'centos_7')


def _test_old_agent_stopped_after_agent_upgrade(ssh_key, module_tmpdir,
                                                test_config, logger, tmpdir,
                                                request, vm_os):
    hosts, username, password = get_test_prerequisites(
        ssh_key, module_tmpdir, test_config, logger, request, vm_os, 2,
    )
    old_manager, new_manager, vm = hosts.instances
    local_snapshot_path = str(tmpdir / 'snapshot.zip')
    snapshot_id = 'snap'

    passed = True
    try:
        hosts.create()

        example = get_example_deployment(
            old_manager, ssh_key, logger,
            '{}_agent_upgrade_test'.format(vm_os),
            test_config, vm=vm,
        )

        if 'windows' in vm_os:
            example.use_windows(username, password)

        example.upload_and_verify_install()

        create_snapshot(old_manager, snapshot_id, logger)
        old_manager.wait_for_all_executions()
        download_snapshot(old_manager, local_snapshot_path, snapshot_id,
                          logger)

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
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)


def _assert_agent_not_running(manager, vm, node_name, tenant):
    with util.set_client_tenant(manager.client, tenant):
        node = manager.client.node_instances.list(node_id=node_name)[0]
    agent = node.runtime_properties['cloudify_agent']
    ssh_command = 'sudo service cloudify-worker-{name} status'.format(
        name=agent['name'],
    )
    response = vm.run_command(ssh_command, warn_only=True).stdout
    assert 'inactive' in response
