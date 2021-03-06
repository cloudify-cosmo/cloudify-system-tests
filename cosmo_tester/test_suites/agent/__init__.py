from cosmo_tester.framework.test_hosts import get_image, Hosts


def get_test_prerequisites(ssh_key, module_tmpdir, test_config, logger,
                           request, vm_os, manager_count=1):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request,
                  manager_count + 1)
    hosts.instances[-1] = get_image('centos', test_config)
    vm = hosts.instances[-1]

    image_name = test_config.platform['{}_image'.format(vm_os)]
    username = test_config['test_os_usernames'][vm_os]

    password = None
    if 'windows' in vm_os:
        password = vm.prepare_for_windows(vm_os)
    else:
        vm.image_name = image_name
        vm.username = username

    return hosts, username, password
