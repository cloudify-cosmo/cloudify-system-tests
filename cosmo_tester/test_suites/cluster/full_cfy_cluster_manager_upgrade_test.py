import pytest

from .cfy_cluster_manager_shared import _cluster_upgrade_test
from cosmo_tester.framework.constants import SUPPORTED_FOR_RPM_UPGRADE


@pytest.mark.full_cluster
@pytest.mark.nine_vms
@pytest.mark.upgrade
@pytest.mark.parametrize('base_version', SUPPORTED_FOR_RPM_UPGRADE)
def test_nine_nodes_cluster_upgrade(base_version, nine_vms, test_config,
                                    ssh_key, logger):
    """Tests the command cfy_cluster_manager upgrade on a 9 nodes cluster."""
    _cluster_upgrade_test(test_config, base_version, nine_vms, ssh_key,
                          logger)
