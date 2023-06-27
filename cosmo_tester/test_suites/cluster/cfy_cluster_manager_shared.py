import json
from os.path import join
import pkg_resources

from retrying import retry
import yaml

from cosmo_tester.framework import util
from cosmo_tester.test_suites.snapshots import upgrade_agents


CLUSTER_MANAGER_RESOURCES_PATH = pkg_resources.resource_filename(
    'cosmo_tester', 'test_suites/cluster/cfy_cluster_manager_resources')
REMOTE_CLUSTER_CONFIG_PATH = '/tmp/cfy_cluster_config.yaml'
REMOTE_LICENSE_PATH = '/tmp/cfy_cluster_manager_license.yaml'
REMOTE_SSH_KEY_PATH = '/tmp/cfy_cluster_manager_ssh_key.pem'


@retry(stop_max_attempt_number=60, wait_fixed=2000)
def _verify_cluster_status(node):
    raw_cluster_status = node.run_command(
        'cfy cluster status --json', warn_only=True, hide_stdout=True)
    assert raw_cluster_status.ok, raw_cluster_status.stderr

    cluster_status = json.loads(raw_cluster_status.stdout)
    assert cluster_status['status'] == 'OK', cluster_status


def _update_three_nodes_config_dict_vms(config_dict, existing_vms_list):
    for i, node in enumerate(existing_vms_list, start=1):
        config_dict['existing_vms']['node-{0}'.format(i)].update({
            'private_ip': str(node.private_ip_address),
            'public_ip': f'{node.ip_address}.example.com'
        })


def _update_nine_nodes_config_dict_vms(config_dict, existing_vms_list):
    for i, node in enumerate(existing_vms_list):
        node_num = (i % 3) + 1
        if i < 3:
            node_name = 'rabbitmq-{0}'.format(node_num)
        elif i < 6:
            node_name = 'postgresql-{0}'.format(node_num)
        else:
            node_name = 'manager-{0}'.format(node_num)

        config_dict['existing_vms'][node_name].update({
            'private_ip': str(node.private_ip_address),
            'public_ip': f'{node.ip_address}.example.com'
        })


def _install_cluster(node, all_nodes, config_dict, test_config, ssh_key,
                     logger, override=False):
    logger.info('Installing cluster')
    node.put_remote_file_content(REMOTE_CLUSTER_CONFIG_PATH,
                                 yaml.dump(config_dict))
    if not override:
        node.put_remote_file(remote_path=REMOTE_SSH_KEY_PATH,
                             local_path=ssh_key.private_key_path)

        node.put_remote_file(remote_path=REMOTE_LICENSE_PATH,
                             local_path=util.get_resource_path(
                                 'test_valid_paying_license.yaml'))

        node.run_command(
            'rpm -qi cloudify-cluster-manager || '
            'sudo yum install -y {0}'.format(
                test_config['cfy_cluster_manager']['rpm_path']), use_sudo=True)

    node.run_command(
        'cfy_cluster_manager install -v --config-path {cfg} {override}'.format(
            cfg=REMOTE_CLUSTER_CONFIG_PATH,
            override='--override' if override else '')
    )

    logger.info('Verifying the cluster status')
    _verify_cluster_status(node)


def _set_rpm_path(cluster_config_dict, test_config, base_version):
    cluster_config_dict['manager_rpm_path'] = util.substitute_testing_version(
        test_config['package_urls']['manager_install_rpm_path'],
        base_version,
        test_config['test_manager']['distro'],
    )


def _upgrade_cluster(nodes_list, manager, test_config, logger):
    logger.info('Upgrading cluster')
    rpm_url = test_config['package_urls']['manager_install_rpm_path']
    manager.run_command(
        'cfy_cluster_manager upgrade -v --config-path {cfg} --upgrade-rpm '
        '{rpm}'.format(
            cfg=REMOTE_CLUSTER_CONFIG_PATH,
            rpm=util.substitute_testing_version(
                rpm_url,
                test_config['testing_version'],
                test_config['test_manager']['distro']),
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
        assert util.get_manager_install_version(node) == version


def _cluster_upgrade_test(test_config, base_version, nodes,
                          ssh_key, logger):
    """Tests upgrade via cfy_cluster_manager upgrade.."""
    nodes_list = [node for node in nodes]
    # Get the first node, or the first manager node (for a nine node)
    manager = nodes_list[-3]
    node_count = len(nodes_list)

    config_dict = _get_config_dict(node_count, test_config,
                                   nodes_list[0].username)

    _set_rpm_path(config_dict, test_config, base_version)

    if node_count == 9:
        _update_nine_nodes_config_dict_vms(config_dict, nodes_list)
    else:
        _update_three_nodes_config_dict_vms(config_dict, nodes_list)

    for node in nodes_list:
        # Because this is removed during cleanup and pre 6.1.0 cloudify yum
        # repo doesn't have logrotate included
        node.run_command('sudo yum install -y logrotate')

    _install_cluster(manager, nodes, config_dict, test_config, ssh_key,
                     logger)

    if base_version.startswith('5.0') or base_version.startswith('5.1'):
        # These base versions use systemd for service management
        for node in nodes:
            # Yes, using the private var is horrible, but we can hopefully
            # retire these versions soon and remove this hack...
            for conf in node.get_installed_configs():
                node.run_command(
                    'echo -e \\\\nservice_management: systemd '
                    '| sudo tee -a {}'.format(conf)
                )
    _install_deployment_with_agent(manager, test_config, ssh_key, logger)

    _upgrade_cluster(nodes_list, manager, test_config, logger)
    upgrade_agents(manager, logger, test_config)


def _install_deployment_with_agent(manager, test_config, ssh_key, logger):
    dep_name = 'example'

    # copy test plugin + example blueprint
    manager.run_command('yum install -y unzip', use_sudo=True)
    manager.put_remote_file(
        '/tmp/test_plugin.zip',
        util.get_resource_path('plugin/test_plugin-1.0.0.zip'),
    )
    manager.run_command('mkdir -p /tmp/example_bp')
    manager.put_remote_file(
        f'/tmp/{dep_name}_bp/{dep_name}.yaml',
        util.get_resource_path('blueprints/compute/example.yaml'),
    )
    manager.run_command('unzip /tmp/test_plugin.zip -d /tmp/test_plugin')

    # upload test plugin + blueprint
    manager.run_command(
        'cfy plugins upload /tmp/test_plugin/*.wgn '
        '-y /tmp/test_plugin/plugin.yaml'
    )
    manager.run_command(
        f'cfy blueprints upload /tmp/{dep_name}_bp/{dep_name}.yaml'
        f' -b {dep_name}'
    )

    # create and install deployment
    inputs = {
        'server_ip': manager.ip_address,
        'path': f'/home/{manager.username}/test_file',
        'content': 'Test',
        'agent_user': manager.username
    }
    with open(ssh_key.private_key_path) as key_handle:
        ssh_key_string = key_handle.read()
    manager.run_command(f'cfy secrets create agent_key -s "{ssh_key_string}"')
    manager.run_command(
        f'cfy deployments create {dep_name} -b {dep_name} -i "{inputs}"')
    manager.run_command(
        f'cfy execution start install -d {dep_name}')


def _get_config_dict(node_count, test_config, vm_user):
    config_file_name = '{}_nodes_config.yaml'.format(node_count)
    config_path = join(CLUSTER_MANAGER_RESOURCES_PATH, config_file_name)
    with open(config_path) as config_file:
        config_dict = yaml.safe_load(config_file)

    basic_config_dict = {
        'ssh_key_path': REMOTE_SSH_KEY_PATH,
        'ssh_user': vm_user,
        'cloudify_license_path': REMOTE_LICENSE_PATH,
        'manager_rpm_path': util.substitute_testing_version(
            test_config['package_urls']['manager_install_rpm_path'],
            test_config['testing_version'],
            test_config['test_manager']['distro'],
        ),
    }

    config_dict.update(basic_config_dict)
    return config_dict
