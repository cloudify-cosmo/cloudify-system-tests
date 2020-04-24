import pytest

from cosmo_tester.framework.test_hosts import TestHosts as Hosts
from cosmo_tester.framework.util import get_attributes
from cosmo_tester.test_suites.snapshots import get_multi_tenant_versions_list

ATTRIBUTES = get_attributes()


@pytest.fixture(scope='function', params=get_multi_tenant_versions_list())
def hosts(request, cfy, ssh_key, module_tmpdir, attributes, logger):
    hosts = Hosts(
        cfy, ssh_key, module_tmpdir,
        attributes, logger, request=request,
        number_of_instances=3, upload_plugins=False,
    )

    hosts.instances[0].image_type = request.param

    vm = hosts.instances[2]
    vm.upload_files = False
    vm.image_name = ATTRIBUTES['centos_7_image_name']
    vm._linux_username = ATTRIBUTES['centos_7_username']

    hosts.create()

    try:
        yield hosts
    finally:
        hosts.destroy()
