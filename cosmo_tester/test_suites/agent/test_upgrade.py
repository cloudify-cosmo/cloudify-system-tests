from cosmo_tester.framework import util
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.test_hosts import Hosts, VM

from cosmo_tester.test_suites.snapshots import (
    create_copy_and_restore_snapshot,
)

from cosmo_tester.test_suites.agent import validate_agent

AGENT_OSES = [
    'centos_7',
    'windows_2012',
]


def test_old_agent_stopped_after_upgrade(ssh_key, module_tmpdir,
                                         test_config, logger, tmpdir,
                                         request):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request,
                  len(AGENT_OSES) + 2)
    old_manager, new_manager = hosts.instances[:2]
    agent_vms = {}

    for idx, agent_os in enumerate(AGENT_OSES):
        hosts.instances[idx + 2] = VM(agent_os, test_config)
        agent_vms[agent_os] = hosts.instances[idx + 2]

    passed = True

    try:
        hosts.create()

        # We're about to be using this manager, let's make sure it's ready
        old_manager.wait_for_ssh()

        # We could create these one at a time in the next loop, but this way
        # we still have them if we need to troubleshoot cross-contamination.
        examples = {
            agent_os: get_example_deployment(
                old_manager, ssh_key, logger,
                'agent_upgrade_{}'.format(agent_os),
                test_config, vm=agent_vms[agent_os]
            )
            for agent_os in AGENT_OSES
        }

        for agent_os in AGENT_OSES:
            example = examples[agent_os]
            vm = agent_vms[agent_os]
            if 'windows' in agent_os:
                example.use_windows(vm.username, vm.password)
            example.upload_and_verify_install()
            validate_agent(old_manager, example, test_config)

        local_snapshot_path = str(tmpdir / 'snapshot.zip')
        snapshot_id = 'snap'

        create_copy_and_restore_snapshot(
            old_manager, new_manager, snapshot_id, local_snapshot_path, logger,
            wait_for_post_restore_commands=True)

        for agent_os in AGENT_OSES:
            example = examples[agent_os]
            vm = agent_vms[agent_os]

            # Before upgrading the agents, the old agent should still be up
            old_manager.run_command(
                'cfy agents validate --tenant-name {}'.format(
                    example.tenant,
                )
            )

            # Upgrade to new agents and stop old agents
            new_manager.run_command(
                'cfy agents install --stop-old-agent --tenant-name {}'.format(
                    example.tenant,
                )
            )
            logger.info('Validating the old agent is indeed down')
            _assert_agent_not_running(old_manager, vm, 'vm', example.tenant,
                                      windows='windows' in agent_os)

        old_manager.stop()

        for agent_os in AGENT_OSES:
            example = examples[agent_os]
            example.manager = new_manager
            example.check_files()
            validate_agent(new_manager, example, test_config, upgrade=True)
            example.uninstall()
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)


def _assert_agent_not_running(manager, vm, node_name, tenant, windows=False):
    with util.set_client_tenant(manager.client, tenant):
        node = manager.client.node_instances.list(node_id=node_name)[0]
    agent = node.runtime_properties['cloudify_agent']

    if windows:
        service_state = vm.run_command(
            '(Get-Service {}).status'.format(agent['name']),
            powershell=True).std_out
        assert service_state.strip().lower() == b'stopped'
    else:
        response = vm.run_command(
            'sudo service cloudify-worker-{} status'.format(agent['name']),
            warn_only=True).stdout
        assert 'inactive' in response.lower()
