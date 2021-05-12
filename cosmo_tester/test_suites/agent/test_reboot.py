import time

import pytest

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.agent import get_test_prerequisites


@pytest.mark.parametrize("vm_os", [
    'ubuntu_16_04',
    'centos_8',
    'centos_7',
    'rhel_7',
    'rhel_8',
    'windows_2012',
])
def test_agent_reboot(ssh_key, module_tmpdir, test_config, logger, vm_os,
                      request):
    hosts, username, password = get_test_prerequisites(
        ssh_key, module_tmpdir, test_config, logger, request, vm_os,
    )
    manager, vm = hosts.instances

    passed = True

    try:
        hosts.create()

        example = get_example_deployment(
            manager, ssh_key, logger, 'agent_reboot_{}'.format(vm_os),
            test_config, vm=vm,
        )
        if 'windows' in vm_os:
            example.use_windows(username, password)
        example.upload_and_verify_install()

        if 'windows' in vm_os:
            vm.run_windows_command('shutdown /r /t 0', warn_only=True)
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
