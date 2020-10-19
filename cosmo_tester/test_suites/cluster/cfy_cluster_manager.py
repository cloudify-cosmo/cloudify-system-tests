import pkg_resources
from os.path import join

import yaml
import pytest
from jinja2 import Environment, FileSystemLoader

from cosmo_tester.framework.util import (generate_ca_cert,
                                         generate_ssl_certificate,
                                         get_resource_path)

RESOURCES_PATH = pkg_resources.resource_filename(
    'cosmo_tester', 'test_suites/cluster/cfy_cluster_manager_resources')
REMOTE_SSH_KEY_PATH = '/tmp/cfy_cluster_manager_ssh_key.pem'
REMOTE_LICENSE_PATH = '/tmp/cfy_cluster_manager_license.yaml'
REMOTE_CERTS_PATH = '/tmp/certs'
REMOTE_CONFIGS_PATH = '/tmp/config_files'


@pytest.fixture()
def basic_config_dict(ssh_key, test_config):
    return {
        'ssh_key_path': REMOTE_SSH_KEY_PATH,
        'ssh_user': 'centos',
        'cloudify_license_path': REMOTE_LICENSE_PATH,
        'manager_rpm_download_link': test_config['cfy_cluster_manager'][
            'manager_install_rpm_path']
    }


@pytest.fixture()
def three_nodes_config_dict(basic_config_dict):
    return _get_config_dict('three_nodes_config.yaml', basic_config_dict)


@pytest.fixture()
def nine_nodes_config_dict(basic_config_dict):
    return _get_config_dict('nine_nodes_config.yaml', basic_config_dict)


@pytest.fixture()
def local_certs_path(tmp_path):
    dir_path = tmp_path / 'certs'
    dir_path.mkdir()
    return dir_path


@pytest.fixture()
def local_config_files(tmp_path):
    dir_path = tmp_path / 'config_files'
    dir_path.mkdir()
    return dir_path


def _get_config_dict(config_file_name, basic_config_dict):
    config_path = join(RESOURCES_PATH, config_file_name)
    with open(config_path) as config_file:
        config_dict = yaml.safe_load(config_file)

    config_dict.update(basic_config_dict)
    return config_dict


def test_create_three_nodes_cluster(three_vms, three_nodes_config_dict,
                                    test_config, ssh_key):
    """Tests that a three nodes cluster is successfully created."""
    node1, node2, node3 = three_vms
    _update_three_nodes_config_dict_vms(three_nodes_config_dict,
                                        [node1, node2, node3])

    _install_cluster(node1, three_nodes_config_dict, test_config, ssh_key)


def test_create_nine_nodes_cluster(nine_vms, nine_nodes_config_dict,
                                   test_config, ssh_key):
    """Tests that a nine nodes cluster is successfully created."""
    node1, node2, node3, node4, node5, node6, node7, node8, node9 = nine_vms
    for i, node in enumerate([node1, node2, node3, node4, node5, node6,
                              node7, node8, node9]):
        node_num = (i % 3) + 1
        if i < 3:
            node_name = 'manager-{0}'.format(node_num)
        elif i < 6:
            node_name = 'rabbitmq-{0}'.format(node_num)
        else:
            node_name = 'postgresql-{0}'.format(node_num)

        nine_nodes_config_dict['existing_vms'][node_name].update({
            'private_ip': str(node.private_ip_address),
            'public_ip': str(node.ip_address)
        })

    _install_cluster(node1, nine_nodes_config_dict, test_config, ssh_key)


def test_create_three_nodes_cluster_using_certificates(
        three_vms, three_nodes_config_dict, test_config,
        ssh_key, local_certs_path, logger):
    """Tests that the supllied certificates are being used in the cluster."""
    node1, node2, node3 = three_vms
    nodes_list = [node1, node2, node3]

    logger.info('Creating certificates')
    _create_certificates(local_certs_path, nodes_list)

    logger.info('Copying certificates to node-1')
    node1.run_command('mkdir -p {0}'.format(REMOTE_CERTS_PATH))
    for cert in local_certs_path.iterdir():
        node1.put_remote_file(local_path=str(cert),
                              remote_path=join(REMOTE_CERTS_PATH, cert.name))

    logger.info('Preparing cluster install configuration file')
    _update_three_nodes_config_dict_vms(three_nodes_config_dict, nodes_list)
    three_nodes_config_dict['ca_cert_path'] = join(REMOTE_CERTS_PATH, 'ca.pem')
    for i, node in enumerate(nodes_list, start=1):
        three_nodes_config_dict['existing_vms']['node-{0}'.format(i)].update({
            'cert_path': join(REMOTE_CERTS_PATH, 'node-{0}.crt'.format(i)),
            'key_path': join(REMOTE_CERTS_PATH, 'node-{0}.key'.format(i))
        })

    logger.info('Installing cluster')
    _install_cluster(node1, three_nodes_config_dict, test_config, ssh_key)

    logger.info('Asserting certs were successfully copied')
    local_ca_path = local_certs_path / 'ca.pem'
    ca_path_in_use = '/etc/cloudify/ssl/cloudify_internal_ca_cert.pem'
    for i, node in enumerate(nodes_list, start=1):
        node_name = 'node-{0}'.format(i)
        logger.info('Asserting certificates for %s', node_name)
        local_node_cert_path = local_certs_path / '{0}.crt'.format(node_name)
        local_node_key_path = local_certs_path / '{0}.key'.format(node_name)
        cert_path_in_use = '/etc/cloudify/ssl/cloudify_internal_cert.pem'
        key_path_in_use = '/etc/cloudify/ssl/cloudify_internal_key.pem'

        assert (local_node_cert_path.read_text() ==
                node.get_remote_file_content(cert_path_in_use))

        assert (local_node_key_path.read_text() ==
                node.get_remote_file_content(key_path_in_use))

        assert (local_ca_path.read_text() ==
                node.get_remote_file_content(ca_path_in_use))


def test_three_nodes_using_provided_config_files(
        three_vms, three_nodes_config_dict, test_config,
        ssh_key, local_certs_path, local_config_files, logger):
    node1, node2, node3 = three_vms
    nodes_list = [node1, node2, node3]
    logger.info('Creating certificates and passing them to the instances')
    node1.run_command('mkdir -p {0}'.format(REMOTE_CERTS_PATH))
    _create_certificates(local_certs_path, nodes_list, pass_certs=True)

    logger.info('Preparing config files')
    _prepare_config_files(nodes_list, local_config_files)
    _update_three_nodes_config_dict_vms(three_nodes_config_dict, nodes_list)
    for i, node in enumerate(nodes_list, start=1):
        three_nodes_config_dict['existing_vms']['node-{0}'.format(i)][
            'config_path'].update({
                'manager_config_path': node.remote_manager_config_path,
                'postgresql_config_path': node.remote_postgresql_config_path,
                'rabbitmq_config_path': node.remote_rabbitmq_config_path
            })

    logger.info('Installing cluster')
    _install_cluster(node1, three_nodes_config_dict, test_config, ssh_key)

    logger.info('Asserting config_files')
    base_cfy_dir = '/etc/cloudify'
    for i, node in enumerate(nodes_list, start=1):
        logger.info(
            'Asserting config.yaml files for {0}'.format('node-{0}'.format(i)))

        assert (node.local_manager_config_path.read_text() ==
                node.get_remote_file_content(
                    join(base_cfy_dir, node.local_manager_config_path.name))
                )

        assert (node.local_postgresql_config_path.read_text() ==
                node.get_remote_file_content(
                    join(base_cfy_dir, node.local_postgresql_config_path.name))
                )

        assert (node.local_rabbitmq_config_path.read_text() ==
                node.get_remote_file_content(
                    join(base_cfy_dir, node.local_rabbitmq_config_path.name))
                )


def _prepare_config_files(nodes_list, local_config_files):
    rabbitmq_cluster = {
        node.hostname: {
            'networks': {
                'default': str(node.private_ip_address)
            }
        } for node in nodes_list
    }

    postgresql_cluster = {
        node.hostname: {
            'ip': str(node.private_ip_address)
        } for node in nodes_list
    }

    nodes_list[0].run_command('mkdir -p {0}'.format(REMOTE_CONFIGS_PATH))
    templates_env = Environment(loader=FileSystemLoader(
        join(RESOURCES_PATH, 'config_files_templates')))
    _prepare_manager_config_files(
        templates_env.get_template('manager_config.yaml'),
        nodes_list, rabbitmq_cluster, postgresql_cluster, local_config_files)
    _prepare_postgresql_config_files(
        templates_env.get_template('postgresql_config.yaml'),
        nodes_list, postgresql_cluster, local_config_files)
    _prepare_rabbitmq_config_files(
        templates_env.get_template('rabbitmq_config.yaml'),
        nodes_list, rabbitmq_cluster, local_config_files)


def _prepare_manager_config_files(template, nodes_list, rabbitmq_cluster,
                                  postgresql_cluster, local_config_files):
    for i, node in enumerate(nodes_list, start=1):
        rendered_date = template.render(
            node=node,
            ca_path=join(REMOTE_CERTS_PATH, 'ca.pem'),
            license_path=REMOTE_LICENSE_PATH,
            rabbitmq_cluster=rabbitmq_cluster,
            postgresql_cluster=postgresql_cluster
        )
        config_name = 'manager-{0}_config.yaml'.format(i)
        remote_config_path = join(REMOTE_CONFIGS_PATH, config_name)
        local_config_file = local_config_files / config_name
        local_config_file.write_text(u'{0}'.format(rendered_date))

        nodes_list[0].put_remote_file(remote_config_path,
                                      str(local_config_file))
        node.local_manager_config_path = local_config_file
        node.remote_manager_config_path = remote_config_path


def _prepare_postgresql_config_files(template, nodes_list, postgresql_cluster,
                                     local_config_files):
    for i, node in enumerate(nodes_list, start=1):
        rendered_date = template.render(
            node=node,
            ca_path=join(REMOTE_CERTS_PATH, 'ca.pem'),
            postgresql_cluster=postgresql_cluster
        )
        config_name = 'postgresql-{0}_config.yaml'.format(i)
        remote_config_path = join(REMOTE_CONFIGS_PATH, config_name)
        local_config_file = local_config_files / config_name
        local_config_file.write_text(u'{0}'.format(rendered_date))

        nodes_list[0].put_remote_file(remote_config_path,
                                      str(local_config_file))
        node.local_postgresql_config_path = local_config_file
        node.remote_postgresql_config_path = remote_config_path


def _prepare_rabbitmq_config_files(template, nodes_list, rabbitmq_cluster,
                                   local_config_files):
    for i, node in enumerate(nodes_list, start=1):
        rendered_date = template.render(
            node=node,
            ca_path=join(REMOTE_CERTS_PATH, 'ca.pem'),
            rabbitmq_cluster=rabbitmq_cluster,
            join_cluster=nodes_list[0].hostname if i > 1 else None
        )
        config_name = 'rabbitmq-{0}_config.yaml'.format(i)
        remote_config_path = join(REMOTE_CONFIGS_PATH, config_name)
        local_config_file = local_config_files / config_name
        local_config_file.write_text(u'{0}'.format(rendered_date))

        nodes_list[0].put_remote_file(remote_config_path,
                                      str(local_config_file))
        node.local_rabbitmq_config_path = local_config_file
        node.remote_rabbitmq_config_path = remote_config_path


def _create_certificates(local_certs_path, nodes_list, pass_certs=False):
    ca_base = str(local_certs_path / 'ca.')
    ca_cert = ca_base + 'pem'
    ca_key = ca_base + 'key'
    generate_ca_cert(ca_cert, ca_key)
    for i, node in enumerate(nodes_list, start=1):
        node_cert = str(local_certs_path / 'node-{0}.crt'.format(i))
        node_key = str(local_certs_path / 'node-{0}.key'.format(i))
        generate_ssl_certificate(
            [node.private_ip_address, node.ip_address],
            node.hostname,
            node_cert,
            node_key,
            ca_cert,
            ca_key
        )
        if pass_certs:
            remote_cert = join(REMOTE_CERTS_PATH, 'node-{0}.crt'.format(i))
            remote_key = join(REMOTE_CERTS_PATH, 'node-{0}.key'.format(i))
            node.cert_path = remote_cert
            node.key_path = remote_key
            node.put_remote_file(remote_cert, node_cert)
            node.put_remote_file(remote_key, node_key)
            node.put_remote_file(join(REMOTE_CERTS_PATH, 'ca.pem'), ca_cert)


def _update_three_nodes_config_dict_vms(config_dict, existing_vms_list):
    for i, node in enumerate(existing_vms_list, start=1):
        config_dict['existing_vms']['node-{0}'.format(i)].update({
            'private_ip': str(node.private_ip_address),
            'public_ip': str(node.ip_address)
        })


def _install_cluster(node, config_dict, test_config, ssh_key):
    node.put_remote_file(remote_path=REMOTE_SSH_KEY_PATH,
                         local_path=ssh_key.private_key_path)

    node.put_remote_file(remote_path=REMOTE_LICENSE_PATH,
                         local_path=get_resource_path(
                             'test_valid_paying_license.yaml'))

    remote_cluster_config_path = '/tmp/cfy_cluster_config.yaml'
    node.put_remote_file_content(remote_cluster_config_path,
                                 yaml.dump(config_dict))

    node.run_command('yum install -y {0}'.format(
        test_config['cfy_cluster_manager']['rpm_path']), use_sudo=True)

    node.run_command('cfy_cluster_manager install -v --config-path '
                     '{0}'.format(remote_cluster_config_path))
