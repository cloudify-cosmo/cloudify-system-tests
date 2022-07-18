import pytest

from .cfy_cluster_manager_shared import _cluster_upgrade_test
from cosmo_tester.framework.constants import SUPPORTED_FOR_RPM_UPGRADE


@pytest.mark.three_vms
@pytest.mark.upgrade
@pytest.mark.parametrize('base_version', SUPPORTED_FOR_RPM_UPGRADE)
def test_three_nodes_cluster_upgrade(base_version, three_vms, test_config,
                                     ssh_key, logger):
    """Tests the command cfy_cluster_manager upgrade on a 3 nodes cluster."""
    _cluster_upgrade_test(test_config, base_version, three_vms, ssh_key,
                          logger)
