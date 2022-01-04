import copy
from os.path import join

import pytest
from jinja2 import Environment, FileSystemLoader
from invoke import UnexpectedExit

from cosmo_tester.framework.util import (generate_ca_cert,
                                         generate_ssl_certificate)
from .cfy_cluster_manager_shared import (
    CLUSTER_MANAGER_RESOURCES_PATH,
    _get_config_dict,
    _install_cluster,
    REMOTE_LICENSE_PATH,
    _update_nine_nodes_config_dict_vms,
    _update_three_nodes_config_dict_vms,
)

REMOTE_CERTS_PATH = '/tmp/certs'
REMOTE_CONFIGS_PATH = '/tmp/config_files'


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


@pytest.mark.three_vms
def test_create_three_nodes_cluster(three_vms, test_config, ssh_key, logger):
    """Tests that a three nodes cluster is successfully created."""
    node1, node2, node3 = three_vms
    three_nodes_config_dict = _get_config_dict(3, test_config, node1.username)
    _update_three_nodes_config_dict_vms(three_nodes_config_dict,
                                        [node1, node2, node3])

    _install_cluster(node1, three_vms, three_nodes_config_dict, test_config,
                     ssh_key, logger)


@pytest.mark.nine_vms
def test_create_nine_nodes_cluster(nine_vms, test_config, ssh_key, logger):
    """Tests that a nine nodes cluster is successfully created."""
    nodes_list = [node for node in nine_vms]
    nine_nodes_config_dict = _get_config_dict(9, test_config,
                                              nodes_list[0].username)
    _update_nine_nodes_config_dict_vms(nine_nodes_config_dict, nodes_list)

    _install_cluster(nodes_list[6], nodes_list, nine_nodes_config_dict,
                     test_config, ssh_key, logger)


@pytest.mark.three_vms
def test_three_nodes_cluster_using_provided_certificates(
        three_vms, test_config, ssh_key, local_certs_path, logger, tmpdir):
    """Tests that the provided certificates are being used in the cluster."""
    node1, node2, node3 = three_vms
    nodes_list = [node1, node2, node3]

    logger.info('Creating certificates')
    _create_certificates(local_certs_path, nodes_list, tmpdir)

    logger.info('Copying certificates to node-1')
    for cert in local_certs_path.iterdir():
        node1.put_remote_file(local_path=str(cert),
                              remote_path=join(REMOTE_CERTS_PATH, cert.name))

    logger.info('Preparing cluster install configuration file')
    three_nodes_config_dict = _get_config_dict(3, test_config, node1.username)
    _update_three_nodes_config_dict_vms(three_nodes_config_dict, nodes_list)
    three_nodes_config_dict['ca_cert_path'] = join(REMOTE_CERTS_PATH, 'ca.pem')
    three_nodes_config_dict['ca_key_path'] = join(REMOTE_CERTS_PATH, 'ca.key')
    for i, node in enumerate(nodes_list, start=1):
        three_nodes_config_dict['existing_vms']['node-{0}'.format(i)].update({
            'cert_path': join(REMOTE_CERTS_PATH, 'node-{0}.crt'.format(i)),
            'key_path': join(REMOTE_CERTS_PATH, 'node-{0}.key'.format(i))
        })

    _install_cluster(node1, three_vms, three_nodes_config_dict, test_config,
                     ssh_key, logger)

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


@pytest.mark.three_vms
def test_three_nodes_using_provided_config_files(
        three_vms, test_config, ssh_key, local_certs_path,
        local_config_files, logger, tmpdir):
    node1, node2, node3 = three_vms
    nodes_list = [node1, node2, node3]

    three_nodes_config_dict = _get_config_dict(3, test_config,
                                               node1.username)
    _install_cluster_using_provided_config_files(
        nodes_list, three_nodes_config_dict, test_config,
        ssh_key, local_certs_path, local_config_files, logger, tmpdir)

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


@pytest.mark.three_vms
def test_three_nodes_cluster_override(
        three_vms, test_config, ssh_key, local_certs_path,
        local_config_files, logger, tmpdir):
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

    three_nodes_config_dict = _get_config_dict(3, test_config, node1.username)
    first_config_dict = copy.deepcopy(three_nodes_config_dict)
    try:
        _install_cluster_using_provided_config_files(
            nodes_list, first_config_dict, test_config, ssh_key,
            local_certs_path, local_config_files, logger, tmpdir,
            cause_error=True)
    except UnexpectedExit:  # This is the error Fabric raises
        logger.info('Error caught. Installing the cluster using override.')
        _update_three_nodes_config_dict_vms(three_nodes_config_dict,
                                            [node1, node2, node3])

        _install_cluster(node1, three_vms, three_nodes_config_dict,
                         test_config, ssh_key, logger, override=True)


@pytest.mark.three_vms
def test_three_nodes_cluster_offline(
        three_vms, test_config, ssh_key, logger):
    """Tests the cluster install in offline environment."""
    node1, node2, node3 = three_vms
    three_nodes_config_dict = _get_config_dict(3, test_config, node1.username)
    local_rpm_path = '/tmp/manager_install_rpm_path.rpm'
    node1.run_command('curl -o {0} {1}'.format(
        local_rpm_path, three_nodes_config_dict['manager_rpm_path']))

    three_nodes_config_dict['manager_rpm_path'] = local_rpm_path
    _update_three_nodes_config_dict_vms(three_nodes_config_dict,
                                        [node1, node2, node3])

    _install_cluster(node1, three_vms, three_nodes_config_dict, test_config,
                     ssh_key, logger)


def _install_cluster_using_provided_config_files(
        nodes_list, three_nodes_config_dict, test_config,
        ssh_key, local_certs_path, local_config_files, logger, tmpdir,
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
    _create_certificates(local_certs_path, nodes_list, tmpdir,
                         pass_certs=True)

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

    _install_cluster(node1, nodes_list, three_nodes_config_dict, test_config,
                     ssh_key, logger, override)


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
        join(CLUSTER_MANAGER_RESOURCES_PATH, 'config_files_templates')))

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


def _create_certificates(local_certs_path, nodes_list, tmpdir,
                         pass_certs=False):
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
            tmpdir,
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
            node.put_remote_file(join(REMOTE_CERTS_PATH, 'ca.key'), ca_key)
