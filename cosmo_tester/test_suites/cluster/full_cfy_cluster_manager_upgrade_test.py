import pytest

from .cfy_cluster_manager_shared import (
    BASE_VERSIONS,
    _cluster_upgrade_test,
)


@pytest.mark.parametrize('base_version', BASE_VERSIONS)
def test_nine_nodes_cluster_upgrade(base_version, nine_vms, test_config,
                                    ssh_key, logger):
    """Tests the command cfy_cluster_manager upgrade on a 9 nodes cluster."""
    _cluster_upgrade_test(test_config, base_version, nine_vms,
                          ssh_key, logger)
