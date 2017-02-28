
import pytest

from cosmo_tester.framework.cloudify_manager import CloudifyManager


@pytest.fixture(scope='module')
def image_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    manager = CloudifyManager.create_image_based(
            cfy, ssh_key, module_tmpdir, attributes, logger)

    yield manager

    manager.destroy()
