import time

import pytest

from cosmo_tester.framework.test_hosts import TestHosts as Hosts
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import get_attributes

ATTRIBUTES = get_attributes()


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
    hosts = Hosts(cfy, ssh_key, module_tmpdir, attributes, logger, 2)
    manager, vm = hosts.instances

    manager.upload_files = False
    manager.restservice_expected = True

    vm.upload_files = False
    image_name = ATTRIBUTES['{}_image_name'.format(vm_os)]
    username = ATTRIBUTES['{}_username'.format(vm_os)]

    password = None
    if 'windows' in vm_os:
        password = vm.prepare_for_windows(image_name, username)
    else:
        vm.image_name = image_name
        vm._linux_username = username

    try:
        hosts.create()

        example = get_example_deployment(
            cfy, manager, ssh_key, logger, 'agent_reboot_{}'.format(vm_os),
            vm=vm,
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
