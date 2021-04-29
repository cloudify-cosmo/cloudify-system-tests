import json
import pkg_resources

from retrying import retry
import yaml

from cosmo_tester.framework.util import get_resource_path


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
            'public_ip': str(node.ip_address)
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
            'public_ip': str(node.ip_address)
        })


def _install_cluster(node, config_dict, test_config, ssh_key, logger,
                     override=False):
    logger.info('Installing cluster')
    node.put_remote_file_content(REMOTE_CLUSTER_CONFIG_PATH,
                                 yaml.dump(config_dict))
    if not override:
        node.put_remote_file(remote_path=REMOTE_SSH_KEY_PATH,
                             local_path=ssh_key.private_key_path)

        node.put_remote_file(remote_path=REMOTE_LICENSE_PATH,
                             local_path=get_resource_path(
                                 'test_valid_paying_license.yaml'))

        node.run_command('yum install -y {0}'.format(
            test_config['cfy_cluster_manager']['rpm_path']), use_sudo=True)

    node.run_command(
        'cfy_cluster_manager install -v --config-path {cfg} {override}'.format(
            cfg=REMOTE_CLUSTER_CONFIG_PATH,
            override='--override' if override else '')
    )

    logger.info('Verifying the cluster status')
    _verify_cluster_status(node)
