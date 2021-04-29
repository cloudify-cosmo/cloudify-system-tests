import pytest

from cosmo_tester.framework.constants import SUPPORTED_RELEASES
from cosmo_tester.framework.util import (
    get_manager_install_version,
    substitute_testing_version,
)

from .cfy_cluster_manager_shared import (
    _install_cluster,
    REMOTE_CLUSTER_CONFIG_PATH,
    _update_nine_nodes_config_dict_vms,
    _update_three_nodes_config_dict_vms,
    _verify_cluster_status,
)


BASE_VERSIONS = [
    version + '-ga'
    for version in SUPPORTED_RELEASES
    if version not in ('master', '5.0.5')
]


@pytest.mark.parametrize('base_version', BASE_VERSIONS)
def test_three_nodes_cluster_upgrade(base_version, three_vms,
                                     three_nodes_config_dict, test_config,
                                     ssh_key, logger):
    """Tests the command cfy_cluster_manager upgrade on a 3 nodes cluster."""
    node1, node2, node3 = three_vms
    nodes_list = [node1, node2, node3]

    _set_rpm_path(three_nodes_config_dict, test_config, base_version)

    _update_three_nodes_config_dict_vms(three_nodes_config_dict, nodes_list)

    _install_cluster(node1, three_nodes_config_dict, test_config, ssh_key,
                     logger)
    _upgrade_cluster(nodes_list, node1, test_config, logger)


@pytest.mark.parametrize('base_version', BASE_VERSIONS)
def test_nine_nodes_cluster_upgrade(base_version, nine_vms,
                                    nine_nodes_config_dict,
                                    test_config, ssh_key, logger):
    """Tests the command cfy_cluster_manager upgrade on a 9 nodes cluster."""
    nodes_list = [node for node in nine_vms]
    manager = nodes_list[6]

    _set_rpm_path(nine_nodes_config_dict, test_config, base_version)

    _update_nine_nodes_config_dict_vms(nine_nodes_config_dict, nodes_list)

    _install_cluster(manager, nine_nodes_config_dict, test_config, ssh_key,
                     logger)
    _upgrade_cluster(nodes_list, manager, test_config, logger)


def _set_rpm_path(cluster_config_dict, test_config, base_version):
    cluster_config_dict['manager_rpm_path'] = substitute_testing_version(
        test_config['package_urls']['manager_install_rpm_path'],
        base_version,
    )


def _upgrade_cluster(nodes_list, manager, test_config, logger):
    logger.info('Upgrading cluster')
    rpm_url = test_config['package_urls']['manager_install_rpm_path']
    manager.run_command(
        'cfy_cluster_manager upgrade -v --config-path {cfg} --upgrade-rpm '
        '{rpm}'.format(
            cfg=REMOTE_CLUSTER_CONFIG_PATH,
            rpm=substitute_testing_version(rpm_url,
                                           test_config['testing_version']),
        )
    )

    logger.info('Validating nodes upgraded')
    assert_manager_install_version_on_nodes(
        nodes_list,
        test_config['testing_version'].split('-')[0],
    )
    logger.info('Verifying the cluster status')
    _verify_cluster_status(manager)


def assert_manager_install_version_on_nodes(nodes_list, version):
    for node in nodes_list:
        assert get_manager_install_version(node) == version
