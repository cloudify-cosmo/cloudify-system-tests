import time

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.test_hosts import Hosts, VM
from cosmo_tester.test_suites.agent import validate_agent, AGENT_OSES


def test_agent_reboot(ssh_key, module_tmpdir, test_config, logger, request):
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
                manager, ssh_key, logger, 'agent_reboot_{}'.format(agent_os),
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
            validate_agent(manager, example, test_config)

            if 'windows' in agent_os:
                vm.run_command('shutdown /r /t 0', warn_only=True)
            else:
                vm.run_command('sudo reboot', warn_only=True)

            # Wait for reboot to at least have started
            time.sleep(10)

            example.uninstall()
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)
