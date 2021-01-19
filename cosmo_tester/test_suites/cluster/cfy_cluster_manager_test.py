import copy
import json
import pkg_resources
from os.path import join

import yaml
import pytest
from retrying import retry
from jinja2 import Environment, FileSystemLoader
from invoke import UnexpectedExit

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
        'manager_rpm_path': test_config['cfy_cluster_manager'][
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
                                    test_config, ssh_key, logger):
    """Tests that a three nodes cluster is successfully created."""
    node1, node2, node3 = three_vms
    _update_three_nodes_config_dict_vms(three_nodes_config_dict,
                                        [node1, node2, node3])

    _install_cluster(node1, three_nodes_config_dict, test_config, ssh_key,
                     logger)


def test_create_nine_nodes_cluster(nine_vms, nine_nodes_config_dict,
                                   test_config, ssh_key, logger):
    """Tests that a nine nodes cluster is successfully created."""
    node1, node2, node3, node4, node5, node6, node7, node8, node9 = nine_vms
    for i, node in enumerate([node1, node2, node3, node4, node5, node6,
                              node7, node8, node9]):
        node_num = (i % 3) + 1
        if i < 3:
            node_name = 'rabbitmq-{0}'.format(node_num)
        elif i < 6:
            node_name = 'postgresql-{0}'.format(node_num)
        else:
            node_name = 'manager-{0}'.format(node_num)

        nine_nodes_config_dict['existing_vms'][node_name].update({
            'private_ip': str(node.private_ip_address),
            'public_ip': str(node.ip_address)
        })

    _install_cluster(node7, nine_nodes_config_dict, test_config, ssh_key,
                     logger)


def test_three_nodes_cluster_using_provided_certificates(
        three_vms, three_nodes_config_dict, test_config,
        ssh_key, local_certs_path, logger):
    """Tests that the provided certificates are being used in the cluster."""
    node1, node2, node3 = three_vms
    nodes_list = [node1, node2, node3]

    logger.info('Creating certificates')
    _create_certificates(local_certs_path, nodes_list)

    logger.info('Copying certificates to node-1')
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

    _install_cluster(node1, three_nodes_config_dict, test_config, ssh_key,
                     logger)

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

    _install_cluster_using_provided_config_files(
        nodes_list, three_nodes_config_dict, test_config,
        ssh_key, local_certs_path, local_config_files, logger)

    logger.info('Asserting config_files')
    cluster_manager_config_files = '/tmp/cloudify_cluster_manager/config_files'
    for i, node in enumerate(nodes_list, start=1):
        logger.info('Asserting config.yaml files for %s', 'node-{0}'.format(i))

        assert (node.local_manager_config_path.read_text() ==
                node.get_remote_file_content(
                    join(cluster_manager_config_files,
                         node.local_manager_config_path.name))
                )

        assert (node.local_postgresql_config_path.read_text() ==
                node.get_remote_file_content(
                    join(cluster_manager_config_files,
                         node.local_postgresql_config_path.name))
                )

        assert (node.local_rabbitmq_config_path.read_text() ==
                node.get_remote_file_content(
                    join(cluster_manager_config_files,
                         node.local_rabbitmq_config_path.name))
                )


def test_three_nodes_cluster_override(
        three_vms, three_nodes_config_dict, test_config,
        ssh_key, local_certs_path, local_config_files, logger):
    """Tests the override install Mechanism.

    The test goes as follows:
        1. Install a three node cluster using an erroneous
           manager config.yaml file. This will of course, cause an error.
        2. Catch the error, and install the cluster from the start using
           the flag `--override`. This step doesn't use generated config.yaml
           files.
    """
    node1, node2, node3 = three_vms
    nodes_list = [node1, node2, node3]

    first_config_dict = copy.deepcopy(three_nodes_config_dict)
    try:
        _install_cluster_using_provided_config_files(
            nodes_list, first_config_dict, test_config, ssh_key,
            local_certs_path, local_config_files, logger, cause_error=True)
    except UnexpectedExit:  # This is the error Fabric raises
        logger.info('Error caught. Installing the cluster using override.')
        _update_three_nodes_config_dict_vms(three_nodes_config_dict,
                                            [node1, node2, node3])

        _install_cluster(node1, three_nodes_config_dict, test_config, ssh_key,
                         logger, override=True)


def test_three_nodes_cluster_offline(
        three_vms, three_nodes_config_dict, test_config, ssh_key, logger):
    """Tests the cluster install in offline environment."""
    node1, node2, node3 = three_vms
    local_rpm_path = '/tmp/manager_install_rpm_path.rpm'
    node1.run_command('curl -o {0} {1}'.format(
        local_rpm_path, three_nodes_config_dict['manager_rpm_path']))

    three_nodes_config_dict['manager_rpm_path'] = local_rpm_path
    _update_three_nodes_config_dict_vms(three_nodes_config_dict,
                                        [node1, node2, node3])

    _install_cluster(node1, three_nodes_config_dict, test_config, ssh_key,
                     logger)


def _install_cluster_using_provided_config_files(
        nodes_list, three_nodes_config_dict, test_config,
        ssh_key, local_certs_path, local_config_files, logger,
        cause_error=False, override=False):
    """Install a Cloudify cluster using generated config files.

    In order to do so, the function:
        1. Generates certificates for each node in the `nodes_list`.
        2. Passes the generated certificates to the different nodes.
        3. Generates the config files for each node based on templates.
        4. Installs the cluster using the generated config files.

    :param cause_error: Whether to cause an error during the installation.
    :param override: Whether to run the installation with override flag.
    """
    node1 = nodes_list[0]
    logger.info('Creating certificates and passing them to the instances')
    _create_certificates(local_certs_path, nodes_list, pass_certs=True)

    logger.info('Preparing config files')
    _prepare_three_nodes_config_files(nodes_list, local_config_files,
                                      cause_error)
    _update_three_nodes_config_dict_vms(three_nodes_config_dict, nodes_list)
    for i, node in enumerate(nodes_list, start=1):
        three_nodes_config_dict['existing_vms']['node-{0}'.format(i)][
            'config_path'].update({
                'manager_config_path': node.remote_manager_config_path,
                'postgresql_config_path': node.remote_postgresql_config_path,
                'rabbitmq_config_path': node.remote_rabbitmq_config_path
            })

    _install_cluster(node1, three_nodes_config_dict, test_config, ssh_key,
                     logger, override)


def _prepare_three_nodes_config_files(nodes_list,
                                      local_config_files,
                                      cause_error=False):
    """Prepare the config files for the three nodes cluster installation.

    :param nodes_list: The three VMs list.
    :param local_config_files: The local config files' directory.
                               It's created using a pytest fixture.
    :param cause_error: If true, an error will be raised during the 1st
                        Manager installation.
    """
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

    manager_postgresql_server = {} if cause_error else postgresql_cluster

    templates_env = Environment(loader=FileSystemLoader(
        join(RESOURCES_PATH, 'config_files_templates')))

    _prepare_manager_config_files(
        templates_env.get_template('manager_config.yaml'), nodes_list,
        rabbitmq_cluster, manager_postgresql_server, local_config_files)

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


def _install_cluster(node, config_dict, test_config, ssh_key, logger,
                     override=False):
    logger.info('Installing cluster')
    remote_cluster_config_path = '/tmp/cfy_cluster_config.yaml'
    node.put_remote_file_content(remote_cluster_config_path,
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
            cfg=remote_cluster_config_path,
            override='--override' if override else '')
    )

    logger.info('Verifying the cluster status')
    _verify_cluster_status(node)


@retry(stop_max_attempt_number=24, wait_fixed=5000)
def _verify_cluster_status(node):
    raw_cluster_status = node.run_command(
        'cfy cluster status --json', warn_only=True, hide_stdout=True)
    assert raw_cluster_status.ok, raw_cluster_status.stderr

    cluster_status = json.loads(raw_cluster_status.stdout)
    assert cluster_status['status'] == 'OK', cluster_status
