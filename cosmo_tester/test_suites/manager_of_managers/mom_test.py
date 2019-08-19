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

import os

import pytest

from cosmo_tester.framework import util
from cosmo_tester.framework.fixtures import image_based_manager # NOQA
from cosmo_tester.test_suites.snapshots import restore_snapshot

from . import constants
from .regional_cluster import (
    FloatingIpRegionalCluster,
    FixedIpRegionalCluster)


fixed_ip_clusters = []
floating_ip_clusters = []

central_hosts = None
ATTRIBUTES = util.get_attributes()


@pytest.fixture(scope='module')  # NOQA
def central_manager(cfy,
                    ssh_key,
                    module_tmpdir,
                    attributes,
                    logger,
                    image_based_manager):  # NOQA
    _upload_resources_to_central_manager(
        cfy, image_based_manager, logger)
    yield image_based_manager


def _upload_resources_to_central_manager(cfy, manager, logger):
    root_resource_dir = os.path.dirname(__file__)

    license_path = os.path.abspath(
        os.path.join(
            root_resource_dir,
            '..', '..', 'resources/test_valid_paying_license.yaml'))
    manager.put_remote_file('/etc/cloudify/license.yaml', license_path)
    manager.run_command(
        'sudo chown cfyuser:cfyuser '
        '/etc/cloudify/license.yaml')

    # At the moment, we don't have a way for the SHBaked CLI
    # to upload the wagon from a private repo.
    # So we download it and upload the local file.
    wagon_save_path = os.path.abspath(
        os.path.join(
            root_resource_dir, constants.MOM_PLUGIN_WGN_NAME))

    util.download_asset(
        constants.MOM_PLUGIN_REPO_PATH,
        constants.MOM_PLUGIN_RELEASE_NAME,
        constants.MOM_PLUGIN_WGN_NAME,
        wagon_save_path,
        os.environ.get('SPIRE_GIT_TOKEN')
    )

    plugin_yaml_save_path = os.path.abspath(
        os.path.join(
            root_resource_dir, 'plugin.yaml'))

    util.download_asset(
        constants.MOM_PLUGIN_REPO_PATH,
        constants.MOM_PLUGIN_RELEASE_NAME,
        'plugin.yaml',
        plugin_yaml_save_path,
        os.environ.get('SPIRE_GIT_TOKEN')
    )

    cfy.plugins.upload(
        wagon_save_path,
        '-y', plugin_yaml_save_path
    )
    cfy.plugins.upload(
        constants.OS_PLUGIN_WGN_URL,
        '-y', constants.OS_PLUGIN_YAML_URL
    )

    manager_install_rpm = \
        ATTRIBUTES.cloudify_manager_install_rpm_url.strip() or \
        util.get_manager_install_rpm_url()

    files_to_download = [
        (manager_install_rpm, constants.INSTALL_RPM_PATH),
        (constants.HW_OS_PLUGIN_WGN_URL, constants.HW_OS_PLUGIN_WGN_PATH),
        (constants.HW_OS_PLUGIN_YAML_URL, constants.HW_OS_PLUGIN_YAML_PATH),
        (constants.HELLO_WORLD_URL, constants.HW_BLUEPRINT_ZIP_PATH)
    ]
    files_to_create = [
        (constants.SH_SCRIPT, constants.SCRIPT_SH_PATH),
        (constants.PY_SCRIPT, constants.SCRIPT_PY_PATH)
    ]

    logger.info('Downloading necessary files to the central manager...')
    for src_url, dst_path in files_to_download:
        manager.run_command(
            'curl -L {0} -o {1}'.format(src_url, dst_path),
            use_sudo=True
        )

    for src_content, dst_path in files_to_create:
        manager.put_remote_file_content(dst_path, src_content, use_sudo=True)

    logger.info('Giving `cfyuser` permissions to downloaded files...')
    files_to_chown = [
        (None, manager.remote_public_key_path),
        (None, manager.remote_private_key_path)
    ]
    for _, dst_path in files_to_download + files_to_create + files_to_chown:
        manager.run_command(
            'chown cfyuser:cfyuser {0}'.format(dst_path),
            use_sudo=True
        )

    logger.info('All permissions granted to `cfyuser`')


@pytest.fixture(scope='module')
def floating_ip_2_regional_clusters(cfy,
                                    central_manager,
                                    attributes,
                                    ssh_key,
                                    module_tmpdir,
                                    logger):
    """ Yield 2 Regional clusters set up with floating IPs """

    global floating_ip_clusters
    if not floating_ip_clusters:
        floating_ip_clusters = _get_regional_clusters(
            'cfy_manager_floating_ip',
            2,
            FloatingIpRegionalCluster,
            cfy, logger, module_tmpdir, attributes, ssh_key, central_manager
        )

    yield floating_ip_clusters

    # We don't need to teardown - this is handled by `teardown_module`


@pytest.fixture(scope='module')
def fixed_ip_2_regional_clusters(cfy, central_manager,
                                 attributes, ssh_key, module_tmpdir, logger):
    """ Yield 2 Regional clusters set up with fixed private IPs """

    global fixed_ip_clusters
    if not fixed_ip_clusters:
        fixed_ip_clusters = _get_regional_clusters(
            'cfy_manager_fixed_ip',
            2,
            FixedIpRegionalCluster,
            cfy, logger, module_tmpdir, attributes, ssh_key, central_manager
        )

    yield fixed_ip_clusters
    # We don't need to teardown - this is handled by `teardown_module`


def _get_regional_clusters(resource_id, number_of_deps, cluster_class,
                           cfy, logger, tmpdir, attributes, ssh_key,
                           central_manager):
    clusters = []

    for i in range(number_of_deps):
        cluster = cluster_class(
            cfy, central_manager, attributes,
            ssh_key, logger, tmpdir, suffix=resource_id
        )
        cluster.blueprint_id = '{0}_bp'.format(resource_id)
        cluster.deployment_id = '{0}_dep_{1}'.format(resource_id, i)
        cluster.blueprint_file = 'blueprints/cluster-blueprint.yaml'
        clusters.append(cluster)

    return clusters


def _do_central_upgrade(floating_ip_2_regional_clusters, central_manager,
                        cfy, tmpdir, logger):

    local_snapshot_path = str(tmpdir / 'snapshot.zip')

    regional_cluster = floating_ip_2_regional_clusters[0]
    regional_cluster.deploy_and_validate()

    cfy.snapshots.create([constants.CENTRAL_MANAGER_SNAP_ID])
    central_manager.wait_for_all_executions()
    cfy.snapshots.download(
        [constants.CENTRAL_MANAGER_SNAP_ID, '-o', local_snapshot_path]
    )

    central_manager.teardown()
    central_manager.bootstrap()
    central_manager.use()
    cfy.snapshots.upload(
        [local_snapshot_path, '-s', constants.CENTRAL_MANAGER_SNAP_ID])
    restore_snapshot(
        central_manager,
        constants.CENTRAL_MANAGER_SNAP_ID,
        cfy, logger, restore_certificates=True)

    cfy.agents.install()


def _do_regional_scale(floating_ip_2_regional_clusters):
    regional_cluster = floating_ip_2_regional_clusters[0]
    regional_cluster.deploy_and_validate()
    regional_cluster.scale()


def _do_regional_heal(regional_cluster):
    regional_cluster.execute_hello_world_workflow('install')
    worker_instance = regional_cluster.manager.client.node_instances.list(
        node_name='additional_workers')[0]
    regional_cluster.heal(worker_instance.id)
    regional_cluster.execute_hello_world_workflow('uninstall')


@pytest.mark.skipif(util.is_redhat(),
                    reason='MoM plugin is only available on Centos')
@pytest.mark.skipif(util.is_community(),
                    reason='Cloudify Community version does '
                           'not support clustering')
def test_regional_cluster_with_floating_ip(
        floating_ip_2_regional_clusters,
        central_manager,
        cfy, tmpdir, logger):
    """
    In this scenario the second cluster is created _alongside_ the first one
    with different floating IPs
    """
    first_cluster = floating_ip_2_regional_clusters[0]
    second_cluster = floating_ip_2_regional_clusters[1]

    first_cluster.deploy_and_validate()

    # Install hello world deployment on Regional manager cluster
    first_cluster.execute_hello_world_workflow('install')
    first_cluster.backup()

    try:
        second_cluster.deploy_and_validate()
    finally:
        # Uninstall hello world deployment from Regional cluster
        second_cluster.execute_hello_world_workflow('uninstall')

    # Upgrade central manager
    _do_central_upgrade(floating_ip_2_regional_clusters,
                        central_manager,
                        cfy,
                        tmpdir,
                        logger)

    # Run Scale workflow against one of the regional clusters
    _do_regional_scale(floating_ip_2_regional_clusters)

    first_cluster.uninstall()
    second_cluster.uninstall()

    # Clean deployments for both clusters
    first_cluster.delete_deployment(use_cfy=True)
    second_cluster.delete_deployment(use_cfy=True)

    # Clean blueprint resource
    first_cluster.clean_blueprints()


@pytest.mark.skipif(util.is_redhat(),
                    reason='MoM plugin is only available on Centos')
@pytest.mark.skipif(util.is_community(),
                    reason='Cloudify Community version does '
                           'not support clustering')
def test_regional_cluster_with_fixed_ip(fixed_ip_2_regional_clusters):
    """
    In this scenario the second cluster is created _instead_ of the first one
    with the same fixed private IPs
    """
    first_cluster = fixed_ip_2_regional_clusters[0]
    second_cluster = fixed_ip_2_regional_clusters[1]

    # Note that we can't easily validate that resources were created on the
    # Regional clusters here, because they're using a fixed private IP, which
    # would not be accessible by a REST client from here. This is why we're
    # only testing that the upgrade has succeeded, and that the IPs were the
    # same for both Regional deployments
    first_cluster.deploy_and_validate()

    # Install hello world deployment on Regional first cluster
    first_cluster.execute_hello_world_workflow('install')

    # Uninstall hello world deployment from Regional first cluster
    first_cluster.execute_hello_world_workflow('uninstall')

    # Take a backup from the first cluster
    first_cluster.backup()

    # Teardown the first cluster
    first_cluster.uninstall()

    # Deploy & validate the second cluster
    second_cluster.deploy_and_validate()

    # Run Heal workflow against one of the regional clusters
    _do_regional_heal(second_cluster)

    # Uninstall clusters
    second_cluster.uninstall()

    # Clean deployments for both clusters
    first_cluster.delete_deployment(use_cfy=True)
    second_cluster.delete_deployment(use_cfy=True)

    # Clean blueprint resource
    first_cluster.clean_blueprints()


def teardown_module():
    """
    First destroy any Regional clusters, then destroy the Central manager.
    Using `teardown_module` because we want to create only a single instance
    of a Central manager, as well as the Floating IP Regional cluster,
    no matter whether we run a single test or a whole module.
    """

    # Destroy all floating ip clusters
    for cluster in floating_ip_clusters:
        cluster.cleanup()

    # Destroy all fixed ip clusters
    for cluster in fixed_ip_clusters:
        cluster.cleanup()

    # Destroy Central manager as a final step
    if central_hosts:
        central_hosts.destroy()

    # Above we downloaded the plugin wagon and YAML
    # from the private repo. Now we are removing it.
    root_resource_dir = os.path.dirname(__file__)
    wagon_save_path = os.path.abspath(
        os.path.join(
            root_resource_dir, constants.MOM_PLUGIN_WGN_NAME))
    plugin_yaml_save_path = os.path.abspath(
        os.path.join(
            root_resource_dir, 'plugin.yaml'))

    files_to_delete = [
        wagon_save_path,
        plugin_yaml_save_path
    ]
    for file_to_delete in files_to_delete:
        os.remove(file_to_delete)
