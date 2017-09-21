
import pytest

from .test_hosts import TestHosts


@pytest.fixture(scope='module')
def image_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    hosts = TestHosts.create_image_based(
            cfy, ssh_key, module_tmpdir, attributes, logger)
    hosts.instances[0].use()

    yield hosts.instances[0]

    hosts.destroy()


@pytest.fixture(scope='module')
def bootstrap_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps a cloudify manager on a VM in rackspace OpenStack."""
    hosts = TestHosts.create_bootstrap_based(
            cfy, ssh_key, module_tmpdir, attributes, logger)
    hosts.instances[0].use()

    yield hosts.instances[0]

    hosts.destroy()
