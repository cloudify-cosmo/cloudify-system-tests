import pytest

from cosmo_tester.framework.test_hosts import TestHosts as Hosts
from cosmo_tester.test_suites.snapshots import get_multi_tenant_versions_list


@pytest.fixture(scope='function', params=get_multi_tenant_versions_list())
def hosts(request, cfy, ssh_key, module_tmpdir, test_config, logger):
    hosts = Hosts(
        cfy, ssh_key, module_tmpdir,
        test_config, logger, request=request,
        number_of_instances=3, upload_plugins=False,
    )

    hosts.instances[0].image_type = request.param

    vm = hosts.instances[2]
    vm.upload_files = False
    vm.image_name = test_config.platform['centos_7_image']
    vm.username = test_config['test_os_usernames']['centos_7']

    hosts.create()

    try:
        yield hosts
    finally:
        hosts.destroy()
