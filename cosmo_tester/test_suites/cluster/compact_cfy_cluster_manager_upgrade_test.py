import pytest

from .cfy_cluster_manager_shared import (
    BASE_VERSIONS,
    _cluster_upgrade_test,
)


@pytest.mark.parametrize('base_version', BASE_VERSIONS)
def test_three_nodes_cluster_upgrade(base_version, three_vms, test_config,
                                     ssh_key, logger):
    """Tests the command cfy_cluster_manager upgrade on a 3 nodes cluster."""
    _cluster_upgrade_test(test_config, base_version, three_vms, ssh_key,
                          logger)
