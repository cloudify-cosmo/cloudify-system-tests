
import pytest

from .test_hosts import TestHosts, BootstrapBasedCloudifyCluster


@pytest.fixture(scope='module')
def image_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    cluster = TestHosts(
            cfy, ssh_key, module_tmpdir, attributes, logger)
    try:
        cluster.create()
        cluster.instances[0].use()
        yield cluster.instances[0]
    finally:
        cluster.destroy()


@pytest.fixture(scope='module')
def bootstrap_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps a cloudify manager on a VM in rackspace OpenStack."""
    cluster = BootstrapBasedCloudifyCluster(cfy, ssh_key, module_tmpdir,
                                            attributes, logger)
    try:
        cluster.create()
        cluster.instances[0].use()
        yield cluster.instances[0]
    finally:
        cluster.destroy()
