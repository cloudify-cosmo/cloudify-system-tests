import pytest

from cosmo_tester.framework.examples.hello_world import HelloWorldExample
from cosmo_tester.framework.util import get_test_tenant, is_community


@pytest.fixture(scope='function')
def hello_worlds(cfy, manager, attributes, ssh_key, tmpdir,
                 logger):
    hellos = get_hello_worlds(cfy, manager, attributes, ssh_key, tmpdir,
                              logger)
    yield hellos
    for hello in hellos:
        hello.cleanup()


def get_hello_worlds(cfy, manager, attributes, ssh_key, tmpdir, logger):
    if is_community():
        tenants = ['default_tenant']
    else:
        tenants = [
            get_test_tenant(name, manager, cfy)
            for name in ('hello1', 'hello2')
        ]
    hellos = []
    for tenant in tenants:
        hello = HelloWorldExample(
            cfy, manager, attributes, ssh_key, logger, tmpdir,
            tenant=tenant, suffix=tenant)
        hello.blueprint_file = 'openstack-blueprint.yaml'
        hello.inputs.update({
            'agent_user': attributes.centos_7_username,
            'image': attributes.centos_7_image_name,
        })
    return hellos
