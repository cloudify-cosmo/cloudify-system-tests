########
# Copyright (c) 2018 Cloudify Platform Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import pytest

from cosmo_tester.framework import util
from cosmo_tester.framework.test_hosts import TestHosts

from cosmo_tester.test_suites.snapshots import restore_snapshot

from . import constants
from .tier_1_clusters import FloatingIpTier1Cluster, FixedIpTier1Cluster

# Important - the MoM plugin is currently only compiled for Centos, so it's
# necessary to run these system tests on Centos as well


# Using module scope here, in order to only bootstrap one Tier 2 manager
@pytest.fixture(scope='module')
def tier_2_manager(cfy, ssh_key, module_tmpdir, attributes, logger):
    """
    Creates a Tier 2 Cloudify manager with all the necessary resources on it
    """
    hosts = TestHosts(
            cfy, ssh_key, module_tmpdir, attributes, logger)
    try:
        hosts.create()
        manager = hosts.instances[0]
        manager.use()
        _upload_resources_to_tier_2_manager(cfy, manager, logger)
        yield manager
    finally:
        hosts.destroy()


def _upload_resources_to_tier_2_manager(cfy, manager, logger):
    cfy.plugins.upload(
        constants.MOM_PLUGIN_WGN_URL,
        '-y', constants.MOM_PLUGIN_YAML_URL
    )
    cfy.plugins.upload(
        constants.OS_PLUGIN_WGN_URL,
        '-y', constants.OS_PLUGIN_YAML_URL
    )

    files_to_download = [
        (util.get_manager_install_rpm_url(), constants.INSTALL_RPM_PATH),
        (constants.OS_201_PLUGIN_WGN_URL, constants.PLUGIN_WGN_PATH),
        (constants.OS_201_PLUGIN_YAML_URL, constants.PLUGIN_YAML_PATH),
        (constants.HELLO_WORLD_URL, constants.BLUEPRINT_ZIP_PATH)
    ]
    files_to_create = [
        (constants.SH_SCRIPT, constants.SCRIPT_SH_PATH),
        (constants.PY_SCRIPT, constants.SCRIPT_PY_PATH)
    ]

    logger.info('Downloading necessary files to the Tier 2 manager...')
    for src_url, dst_path in files_to_download:
        manager.run_command(
            'curl -L {0} -o {1}'.format(src_url, dst_path),
            use_sudo=True
        )

    for src_content, dst_path in files_to_create:
        manager.put_remote_file_content(dst_path, src_content, use_sudo=True)

    logger.info('Giving `cfyuser` permissions to downloaded files...')
    for _, dst_path in files_to_download + files_to_create:
        manager.run_command(
            'chown cfyuser:cfyuser {0}'.format(dst_path),
            use_sudo=True
        )
    logger.info('All permissions granted to `cfyuser`')


@pytest.fixture(scope='module')
def floating_ip_2_tier_1_clusters(cfy, tier_2_manager,
                                  attributes, ssh_key, module_tmpdir, logger):
    """ Yield 2 Tier 1 clusters set up with floating IPs """

    clusters = _get_tier_1_clusters(
        'cfy_manager_floating_ip',
        2,
        FloatingIpTier1Cluster,
        cfy, logger, module_tmpdir, attributes, ssh_key, tier_2_manager
    )

    yield clusters
    for cluster in clusters:
        cluster.cleanup()


@pytest.fixture(scope='module')
def fixed_ip_2_tier_1_clusters(cfy, tier_2_manager,
                               attributes, ssh_key, module_tmpdir, logger):
    """ Yield 2 Tier 1 clusters set up with fixed private IPs """

    clusters = _get_tier_1_clusters(
        'cfy_manager_fixed_ip',
        2,
        FixedIpTier1Cluster,
        cfy, logger, module_tmpdir, attributes, ssh_key, tier_2_manager
    )

    yield clusters
    for cluster in clusters:
        cluster.cleanup()


def _get_tier_1_clusters(resource_id, number_of_deps, cluster_class,
                         cfy, logger, tmpdir, attributes, ssh_key,
                         tier_2_manager):
    clusters = []

    for i in range(number_of_deps):
        cluster = cluster_class(
            cfy, tier_2_manager, attributes,
            ssh_key, logger, tmpdir, suffix=resource_id
        )
        cluster.blueprint_id = '{0}_bp'.format(resource_id)
        cluster.deployment_id = '{0}_dep_{1}'.format(resource_id, i)
        cluster.blueprint_file = 'blueprint.yaml'
        clusters.append(cluster)

    return clusters


def test_tier_1_cluster_staged_upgrade(floating_ip_2_tier_1_clusters):
    """
    In this scenario the second cluster is created _alongside_ the first one
    with different floating IPs
    """
    first_cluster = floating_ip_2_tier_1_clusters[0]
    second_cluster = floating_ip_2_tier_1_clusters[1]

    first_cluster.deploy_and_validate()
    first_cluster.backup()

    second_cluster.deploy_and_validate()


def test_tier_1_cluster_inplace_upgrade(fixed_ip_2_tier_1_clusters):
    """
    In this scenario the second cluster is created _instead_ of the first one
    with the same fixed private IPs
    """
    first_cluster = fixed_ip_2_tier_1_clusters[0]
    second_cluster = fixed_ip_2_tier_1_clusters[1]

    # Note that we can't easily validate that resources were created on the
    # Tier 1 clusters here, because they're using a fixed private IP, which
    # would not be accessible by a REST client from here. This is why we're
    # only testing that the upgrade has succeeded, and that the IPs were the
    # same for both Tier 1 deployments
    first_cluster.deploy_and_validate()
    first_cluster.backup()
    first_cluster.uninstall()

    second_cluster.deploy_and_validate()


def test_tier_2_upgrade(floating_ip_2_tier_1_clusters, tier_2_manager,
                        cfy, tmpdir, logger):
    local_snapshot_path = str(tmpdir / 'snapshot.zip')

    cfy.snapshots.create([constants.TIER_2_SNAP_ID])
    tier_2_manager.wait_for_all_executions()
    cfy.snapshots.download(
        [constants.TIER_2_SNAP_ID, '-o', local_snapshot_path]
    )

    tier_2_manager.teardown()
    tier_2_manager.bootstrap()
    tier_2_manager.use()

    _upload_resources_to_tier_2_manager(cfy, tier_2_manager, logger)

    cfy.snapshots.upload([local_snapshot_path, '-s', constants.TIER_2_SNAP_ID])
    restore_snapshot(tier_2_manager, constants.TIER_2_SNAP_ID, cfy, logger,
                     restore_certificates=True)

    cfy.agents.install()

    # This will only work properly if the Tier 2 manager was restored correctly
    for cluster in floating_ip_2_tier_1_clusters:
        cluster.uninstall()
