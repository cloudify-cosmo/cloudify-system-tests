import os

import pytest

from cosmo_tester.framework import util
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    download_snapshot,
    restore_snapshot,
    upload_snapshot,
)

from . import constants
from .regional_cluster import (
    FloatingIpRegionalCluster,
    FixedIpRegionalCluster)


fixed_ip_clusters = []
floating_ip_clusters = []

central_hosts = None
# This won't work at all, and has just been set like this to make pytest's
# collectonly work. This will be fixed as part of CY-2607
ATTRIBUTES = {}


@pytest.fixture(scope='module')
def central_manager(ssh_key,
                    module_tmpdir,
                    attributes,
                    logger,
                    image_based_manager):
    _upload_resources_to_central_manager(image_based_manager, logger)
    yield image_based_manager


def _upload_resources_to_central_manager(manager, logger):
    root_resource_dir = os.path.dirname(__file__)

    license_path = os.path.abspath(
        os.path.join(
            root_resource_dir,
            '..', '..', 'resources/test_valid_paying_license.yaml'))
    manager.put_remote_file('/etc/cloudify/license.yaml', license_path)
    manager.run_command(
        'sudo chown cfyuser:cfyuser '
        '/etc/cloudify/license.yaml')

    # TODO: Here we need to upload the spire plugin (in a zip with its yaml)
    # This has been temporarily removed as it should be added into the config
    # rather than relying on env vars that are only obvious if you know about
    # them or if you wait for a bunch of VMs to be deployed and then see them
    # in an exception.
    # This was previously uploading the spire, openstack, and ansible plugins.
    # Related jira: CY-2607

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
        manager.put_remote_file_content(dst_path, src_content)

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
    openstack_config = util.get_openstack_config()
    secrets_to_create = {
        'etcd_cluster_token': ATTRIBUTES.cloudify_password,
        'etcd_root_password': ATTRIBUTES.cloudify_password,
        'etcd_patroni_password': ATTRIBUTES.cloudify_password,
        'patroni_rest_password': ATTRIBUTES.cloudify_password,
        'postgres_replicator_password': ATTRIBUTES.cloudify_password,
        'postgres_password': ATTRIBUTES.cloudify_password,
        'manager_admin_password': ATTRIBUTES.cloudify_password,
        'openstack_auth_url': openstack_config['auth_url'],
        'openstack_username': openstack_config['username'],
        'openstack_password': openstack_config['password'],
        'openstack_tenant_name': openstack_config['tenant_name'],
        'openstack_region': os.environ['OS_REGION_NAME'],
        'manager_admin_username': ATTRIBUTES.cloudify_username
    }

    for k, v in secrets_to_create.items():
        manager.secrets.create(k, v)
    logger.info('Created all password secrets.')


@pytest.fixture(scope='module')
def floating_ip_2_regional_clusters(central_manager,
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
            logger, module_tmpdir, attributes, ssh_key, central_manager
        )

    yield floating_ip_clusters

    # We don't need to teardown - this is handled by `teardown_module`


@pytest.fixture(scope='module')
def fixed_ip_2_regional_clusters(central_manager,
                                 attributes, ssh_key, module_tmpdir, logger):
    """ Yield 2 Regional clusters set up with fixed private IPs """

    global fixed_ip_clusters
    if not fixed_ip_clusters:
        fixed_ip_clusters = _get_regional_clusters(
            'cfy_manager_fixed_ip',
            2,
            FixedIpRegionalCluster,
            logger, module_tmpdir, attributes, ssh_key, central_manager
        )

    yield fixed_ip_clusters
    # We don't need to teardown - this is handled by `teardown_module`


def _get_regional_clusters(resource_id, number_of_deps, cluster_class,
                           logger, tmpdir, attributes, ssh_key,
                           central_manager):
    clusters = []

    for i in range(number_of_deps):
        cluster = cluster_class(
            central_manager, attributes,
            ssh_key, logger, tmpdir, suffix=resource_id
        )
        cluster.blueprint_id = '{0}_bp'.format(resource_id)
        cluster.deployment_id = '{0}_dep_{1}'.format(resource_id, i)
        cluster.blueprint_file = 'blueprints/cluster-blueprint.yaml'
        clusters.append(cluster)

    return clusters


def _do_central_upgrade(regional_cluster, central_manager,
                        tmpdir, logger):

    local_snapshot_path = str(tmpdir / 'snapshot.zip')

    regional_cluster.deploy_and_validate()

    create_snapshot(constants.CENTRAL_MANAGER_SNAP_ID)
    download_snapshot(central_manager,
                      local_snapshot_path,
                      constants.CENTRAL_MANAGER_SNAP_ID,
                      logger)

    central_manager.teardown()
    central_manager.bootstrap()

    upload_snapshot(central_manager, local_snapshot_path,
                    constants.CENTRAL_MANAGER_SNAP_ID, logger)
    restore_snapshot(central_manager, constants.CENTRAL_MANAGER_SNAP_ID,
                     logger)

    central_manager.run_command('cfy agents install')


def _do_regional_scale(regional_cluster):
    regional_cluster.deploy_and_validate()
    regional_cluster.scale()


def _do_regional_heal(regional_cluster):
    regional_cluster.execute_hello_world_workflow('install')
    worker_instance = regional_cluster.manager.client.node_instances.list(
        deployment_id=regional_cluster.deployment_id,
        node_name='cloudify_manager_worker')[0]
    regional_cluster.heal(worker_instance.id)
    regional_cluster.execute_hello_world_workflow('uninstall')


@pytest.mark.skipif(False,
                    reason='MoM plugin is only available on Centos')
@pytest.mark.skipif(False,
                    reason='Cloudify Community version does '
                           'not support clustering')
def test_regional_cluster_with_floating_ip(
        floating_ip_2_regional_clusters,
        central_manager,
        tmpdir, logger):
    """
    In this scenario the second cluster is created _alongside_ the first one
    with different floating IPs
    """
    first_cluster = floating_ip_2_regional_clusters[0]
    second_cluster = floating_ip_2_regional_clusters[1]

    first_cluster.deploy_and_validate(timeout=6000)

    # Install hello world deployment on Regional manager cluster
    first_cluster.execute_hello_world_workflow('install')
    first_cluster.execute_hello_world_workflow('uninstall')

    first_cluster.backup()

    first_cluster.uninstall(timeout=6000)

    second_cluster.deploy_and_validate(timeout=6000)

    # Run Scale workflow against one of the regional clusters
    _do_regional_scale(second_cluster)

    # Upgrade central manager
    _do_central_upgrade(second_cluster,
                        central_manager,
                        tmpdir,
                        logger)

    second_cluster.uninstall(timeout=6000)

    # Clean deployments for both clusters
    first_cluster.delete_deployment()
    second_cluster.delete_deployment()

    # Clean blueprint resource
    first_cluster.clean_blueprints()


@pytest.mark.skipif(False,
                    reason='MoM plugin is only available on Centos')
@pytest.mark.skipif(False,
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
    first_cluster.deploy_and_validate(timeout=6000)

    # Install hello world deployment on Regional first cluster
    first_cluster.execute_hello_world_workflow('install')
    # Uninstall hello world deployment from Regional first cluster
    first_cluster.execute_hello_world_workflow('uninstall')

    # Take a backup from the first cluster
    first_cluster.backup()

    # Teardown the first cluster
    first_cluster.uninstall(timeout=6000)

    # Deploy & validate the second cluster
    second_cluster.deploy_and_validate(timeout=6000)

    # Run Heal workflow against one of the regional clusters
    _do_regional_heal(second_cluster)

    # Uninstall clusters
    second_cluster.uninstall(timeout=6000)

    # Clean deployments for both clusters
    first_cluster.delete_deployment()
    second_cluster.delete_deployment()

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
