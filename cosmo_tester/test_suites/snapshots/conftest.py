import pytest

from cosmo_tester.framework.test_hosts import Hosts, VM
from cosmo_tester.test_suites.snapshots import get_multi_tenant_versions_list


@pytest.fixture(scope='function')
def hosts(request, ssh_key, module_tmpdir, test_config, logger):
    old_managers = get_multi_tenant_versions_list()

    hosts = Hosts(
        ssh_key, module_tmpdir,
        test_config, logger, request,
        number_of_instances=3 + len(old_managers),
    )

    new_mgr = hosts.instances[0] = VM('master', test_config)
    win_vm = hosts.instances[1] = VM('windows_2012', test_config)
    lin_vm = hosts.instances[2] = VM('rhel_8', test_config)

    old_mgr_mappings = {}
    for idx, old_mgr in enumerate(old_managers):
        hosts.instances[idx + 3] = VM(old_mgr, test_config)
        old_mgr_mappings[old_mgr] = hosts.instances[idx + 3]

    hosts.create()
    yield new_mgr, win_vm, lin_vm, old_mgr_mappings
    hosts.destroy()
