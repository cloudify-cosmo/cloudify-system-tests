import pytest

from cosmo_tester.framework.examples.hello_world import HelloWorldExample

from .cluster import CloudifyCluster
from .util import get_hello_worlds


@pytest.fixture(scope='module')
def image_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    cluster = CloudifyCluster.create_image_based(
            cfy, ssh_key, module_tmpdir, attributes, logger)
    cluster.managers[0].use()

    yield cluster.managers[0]

    cluster.destroy()


@pytest.fixture(scope='module')
def bootstrap_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps a cloudify manager on a VM in rackspace OpenStack."""
    cluster = CloudifyCluster.create_bootstrap_based(
            cfy, ssh_key, module_tmpdir, attributes, logger)
    cluster.managers[0].use()

    yield cluster.managers[0]

    cluster.destroy()


@pytest.fixture(scope='function')
def hello_worlds(cfy, manager, attributes, ssh_key, tmpdir,
                 logger):
    hellos = get_hello_worlds(cfy, manager, attributes, ssh_key, tmpdir,
                              logger)
    yield hellos
    for hello in hellos:
        hello.cleanup()
