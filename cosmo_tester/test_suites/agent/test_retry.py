import time

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.test_hosts import Hosts, VM

AGENT_OSES = [
    'centos_8',
    'rhel_8',
    'windows_2012',
]


def test_agent_retry(ssh_key, module_tmpdir, test_config, logger, request):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request,
                  len(AGENT_OSES) + 1)
    manager = hosts.instances[0]
    agent_vms = {}

    for idx, agent_os in enumerate(AGENT_OSES):
        hosts.instances[idx + 1] = VM(agent_os, test_config)
        agent_vms[agent_os] = hosts.instances[idx + 1]

    passed = True

    try:
        hosts.create()

        # We could create these one at a time in the next loop, but this way
        # we still have them if we need to troubleshoot cross-contamination.
        examples = {
            agent_os: get_example_deployment(
                manager, ssh_key, logger, 'agent_retry_{}'.format(agent_os),
                test_config, vm=agent_vms[agent_os]
            )
            for agent_os in AGENT_OSES
        }

        for agent_os in AGENT_OSES:
            example = examples[agent_os]
            vm = agent_vms[agent_os]

            example.inputs['wait'] = 20
            example.upload_blueprint()
            example.create_deployment()
            if 'windows' in agent_os:
                example.use_windows(vm.username, vm.password)

            execution_id = manager.client.executions.start(
                example.deployment_id, 'install').id
            time.sleep(3)  # wait for the mgmtworker to get the execution

            # Disable communication with agent for a few moments
            manager.run_command(
                f'iptables -I INPUT 1 -p tcp -s {vm.ip_address} -j DROP',
                use_sudo=True
            )

            time.sleep(60)

            # Re-enable the communication with agent
            manager.run_command('iptables -D INPUT 1', use_sudo=True)

            # Give agent some time for the retry
            time.sleep(30)

            # Validate the execution
            execution = manager.client.executions.get(execution_id)
            assert execution.status == 'terminated'

            example.uninstall()
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)
