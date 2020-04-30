import time

import pytest

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.agent import get_test_prerequisites


@pytest.mark.parametrize("vm_os", [
    'ubuntu_14_04',
    'ubuntu_16_04',
    'centos_6',
    'centos_7',
    'rhel_6',
    'rhel_7',
    'windows_2012',
])
def test_agent_reboot(cfy, ssh_key, module_tmpdir, attributes, logger, vm_os):
    hosts, username, password = get_test_prerequisites(
        cfy, ssh_key, module_tmpdir, attributes, logger, vm_os,
    )
    manager, vm = hosts.instances

    try:
        hosts.create()

        example = get_example_deployment(
            manager, ssh_key, logger, 'agent_reboot_{}'.format(vm_os), vm=vm,
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
    finally:
        hosts.destroy()
