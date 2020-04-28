from cosmo_tester.framework.test_hosts import TestHosts as Hosts
from cosmo_tester.framework.util import get_attributes

ATTRIBUTES = get_attributes()


def get_test_prerequisites(cfy, ssh_key, module_tmpdir, attributes, logger,
                           vm_os):
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

    return hosts, username, password
