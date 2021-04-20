from cosmo_tester.framework.test_hosts import Hosts, VM


def get_test_prerequisites(ssh_key, module_tmpdir, test_config, logger,
                           request, vm_os, manager_count=1):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request,
                  manager_count + 1)
    hosts.instances[-1] = VM(vm_os, test_config)
    vm = hosts.instances[-1]

    return hosts, vm.username, vm.password
