
import pytest

from .cluster import CloudifyCluster, MANAGERS
from .util import get_test_tenants, create_test_tenants


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
def image_based_manager_with_tenants(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """
        Creates a cloudify manager with tenants and targets for singlehost
        deployments for those tenants.
    """
    tenants = get_test_tenants()

    manager_types = ['master']
    target_vms = ['notamanager' for i in range(len(tenants))]
    managers = [
        MANAGERS[mgr_type](upload_plugins=False)
        for mgr_type in manager_types + target_vms
    ]

    cluster = CloudifyCluster.create_image_based(
            cfy,
            ssh_key,
            module_tmpdir,
            attributes,
            logger,
            managers=managers,
            )
    cluster.managers[0].use()
    create_test_tenants(cfy)

    yield cluster

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
