import os
import json
import time

import pytest
from os.path import join, dirname
from jinja2 import Environment, FileSystemLoader

from cosmo_tester.framework.test_hosts import Hosts
from cosmo_tester.framework import util

CONFIG_DIR = join(dirname(__file__), 'config')


def skip(*args, **kwargs):
    return True


@pytest.fixture()
def brokers(cfy, ssh_key, module_tmpdir, test_config, logger, request):
    for _brokers in _get_hosts(cfy, ssh_key, module_tmpdir, test_config,
                               logger, request, broker_count=3):
        yield _brokers


@pytest.fixture()
def broker(cfy, ssh_key, module_tmpdir, test_config, logger, request):
    for _brokers in _get_hosts(cfy, ssh_key, module_tmpdir, test_config,
                               logger, request, broker_count=1):
        yield _brokers[0]


@pytest.fixture()
def dbs(cfy, ssh_key, module_tmpdir, test_config, logger, request):
    for _dbs in _get_hosts(cfy, ssh_key, module_tmpdir, test_config,
                           logger, request, db_count=3):
        yield _dbs


@pytest.fixture()
def brokers_and_manager(cfy, ssh_key, module_tmpdir, test_config, logger,
                        request):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           test_config, logger, request,
                           broker_count=2, manager_count=1):
        yield _vms


@pytest.fixture()
def brokers3_and_manager(cfy, ssh_key, module_tmpdir, test_config, logger,
                         request):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           test_config, logger, request,
                           broker_count=3, manager_count=1):
        yield _vms


@pytest.fixture()
def full_cluster(cfy, ssh_key, module_tmpdir, test_config, logger, request):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           test_config, logger, request,
                           broker_count=3, db_count=3, manager_count=2,
                           pre_cluster_rabbit=True):
        yield _vms


@pytest.fixture()
def cluster_with_lb(cfy, ssh_key, module_tmpdir, test_config, logger,
                    request):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           test_config, logger, request,
                           broker_count=1, db_count=1, manager_count=3,
                           use_load_balancer=True, pre_cluster_rabbit=True):
        yield _vms


@pytest.fixture()
def cluster_missing_one_db(cfy, ssh_key, module_tmpdir, test_config,
                           logger, request):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           test_config, logger, request,
                           skip_bootstrap_list=['db3'],
                           broker_count=3, db_count=3, manager_count=2,
                           pre_cluster_rabbit=True):
        yield _vms


@pytest.fixture()
def cluster_with_single_db(cfy, ssh_key, module_tmpdir, test_config,
                           logger, request):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir,
                           test_config, logger, request,
                           broker_count=3, db_count=1, manager_count=2,
                           pre_cluster_rabbit=True):
        yield _vms


@pytest.fixture()
def minimal_cluster(cfy, ssh_key, module_tmpdir, test_config, logger,
                    request):
    for _vms in _get_hosts(cfy, ssh_key, module_tmpdir, test_config, logger,
                           request,
                           broker_count=1, db_count=1, manager_count=2,
                           pre_cluster_rabbit=True):
        yield _vms


def _get_hosts(cfy, ssh_key, module_tmpdir, test_config, logger, request,
               broker_count=0, manager_count=0, db_count=0,
               use_load_balancer=False, skip_bootstrap_list=None,
               # Pre-cluster rabbit determines whether to cluster rabbit
               # during the bootstrap.
               # High security will pre-set all certs (not just required ones)
               # and use postgres client certs.
               pre_cluster_rabbit=False, high_security=True):
    if skip_bootstrap_list is None:
        skip_bootstrap_list = []
    hosts = Hosts(
        cfy, ssh_key, module_tmpdir, test_config, logger, request,
        number_of_instances=broker_count + db_count + manager_count + (
            1 if use_load_balancer else 0
        ),
        bootstrappable=True)

    tempdir = hosts._tmpdir

    try:
        for node in hosts.instances:
            node.verify_services_are_running = skip
            node.upload_necessary_files = skip

        hosts.create()

        for node in hosts.instances:
            node.wait_for_ssh()
            # This needs to happen before we start bootstrapping nodes
            # because the hostname is used by nodes that are being
            # bootstrapped with reference to nodes that may not have been
            # bootstrapped yet.
            node.hostname = str(
                node.run_command('hostname -s').stdout.strip())

        brokers = hosts.instances[:broker_count]
        dbs = hosts.instances[broker_count:broker_count + db_count]
        managers = hosts.instances[broker_count + db_count:
                                   broker_count + db_count + manager_count]
        if use_load_balancer:
            lb = hosts.instances[broker_count + db_count + manager_count]

        for node_num, node in enumerate(brokers, start=1):
            _bootstrap_rabbit_node(node, node_num, brokers,
                                   skip_bootstrap_list, pre_cluster_rabbit,
                                   tempdir, logger)

        for node_num, node in enumerate(dbs, start=1):
            _bootstrap_db_node(node, node_num, dbs, skip_bootstrap_list,
                               high_security, tempdir, logger)

        # Ensure all backend nodes are up before installing managers
        for node in brokers + dbs:
            if node.friendly_name in skip_bootstrap_list:
                continue
            while not node.bootstrap_is_complete():
                logger.info('Checking state of {}'.format(node.friendly_name))
                time.sleep(5)

        for node_num, node in enumerate(managers, start=1):
            _bootstrap_manager_node(node, node_num, dbs, brokers,
                                    skip_bootstrap_list, pre_cluster_rabbit,
                                    high_security, tempdir, logger,
                                    test_config)

        if len(managers) > 1:
            _configure_status_reporters(managers, brokers, dbs,
                                        skip_bootstrap_list, logger)
        if use_load_balancer:
            _bootstrap_lb_node(lb, managers, tempdir, logger)

        logger.info('All nodes are bootstrapped.')

        yield hosts.instances
    finally:
        hosts.destroy()


def _base_prep(node, tempdir):
    with node.ssh() as fabric_ssh:
        fabric_ssh.run(
            'mkdir -p /tmp/bs_logs'
        )

        fabric_ssh.run(
            'echo {name} > /tmp/bs_logs/0_node_name'.format(
                name=node.friendly_name,
            )
        )

    ca_base = os.path.join(tempdir, 'ca.')
    ca_cert = ca_base + 'cert'
    ca_key = ca_base + 'key'

    if not os.path.exists(ca_cert):
        util.generate_ca_cert(ca_cert, ca_key)

    cert_base = os.path.join(tempdir, '{node_friendly_name}.{extension}')

    node_cert = cert_base.format(node_friendly_name=node.friendly_name,
                                 extension='crt')
    node_key = cert_base.format(node_friendly_name=node.friendly_name,
                                extension='key')

    util.generate_ssl_certificate(
        [node.friendly_name, node.hostname,
         node.private_ip_address,
         node.ip_address],
        node.hostname,
        node_cert,
        node_key,
        ca_cert,
        ca_key,
    )

    remote_cert = '/tmp/' + node.friendly_name + '.crt'
    remote_key = '/tmp/' + node.friendly_name + '.key'
    remote_ca = '/tmp/ca.crt'

    node.put_remote_file(
        local_path=node_cert,
        remote_path=remote_cert,
    )
    node.put_remote_file(
        local_path=node_key,
        remote_path=remote_key,
    )
    node.put_remote_file(
        local_path=ca_cert,
        remote_path=remote_ca,
    )

    node.local_cert = node_cert
    node.remote_cert = remote_cert
    node.local_key = node_key
    node.remote_key = remote_key
    node.local_ca = ca_cert
    node.remote_ca = remote_ca


def _bootstrap_rabbit_node(node, rabbit_num, brokers, skip_bootstrap_list,
                           pre_cluster_rabbit, tempdir, logger):
    node.friendly_name = 'rabbit' + str(rabbit_num)

    _base_prep(node, tempdir)

    logger.info('Preparing rabbit {}'.format(node.hostname))

    join_target = ''
    if pre_cluster_rabbit and rabbit_num != 1:
        join_target = brokers[0].hostname

    if pre_cluster_rabbit:
        rabbit_nodes = {
            broker.hostname: {
                'networks': {
                    'default': str(broker.private_ip_address)
                }
            }
            for broker in brokers
        }
    else:
        rabbit_nodes = {}

    node.install_config['rabbitmq'] = {
        'ca_path': '/tmp/ca.crt',
        'cert_path': node.remote_cert,
        'key_path': node.remote_key,
        'erlang_cookie': 'thisisacookiefortestingnotproduction',
        'cluster_members': rabbit_nodes,
        'nodename': node.hostname,
        'join_cluster': join_target,
    }
    node.install_config['services_to_install'] = ['queue_service']

    if node.friendly_name in skip_bootstrap_list:
        return

    if pre_cluster_rabbit and rabbit_num == 1:
        node.bootstrap(blocking=True, enter_sanity_mode=False,
                       restservice_expected=False)
    else:
        node.bootstrap(blocking=False, enter_sanity_mode=False,
                       restservice_expected=False)


def _bootstrap_db_node(node, db_num, dbs, skip_bootstrap_list, high_security,
                       tempdir, logger):
    node.friendly_name = 'db' + str(db_num)

    _base_prep(node, tempdir)

    logger.info('Preparing db {}'.format(node.hostname))

    node.pg_password = 'xsqkopcdsog\'je"d<sub;n>osz ,po#qe'

    node.install_config['postgresql_server'] = {
        'postgres_password': node.pg_password,
        'cert_path': node.remote_cert,
        'key_path': node.remote_key,
        'ca_path': '/tmp/ca.crt',
    }
    node.install_config['services_to_install'] = ['database_service']

    server_conf = node.install_config['postgresql_server']
    if len(dbs) > 1:
        db_nodes = {db.hostname: {'ip': str(db.private_ip_address)}
                    for db in dbs}
        server_conf['cluster'] = {
            'nodes': db_nodes,
            'etcd': {
                'cluster_token': 'jsdiogjdsiogjdiaogjdioagjiodsa',
                'root_password': 'fgiosagjisoagjiosagjiosajgios',
                'patroni_password': 'jgiosagjiosagjsaiogjsio',
            },
            'patroni': {
                'rest_user': 'patroni',
                'rest_password': 'dfsjuiogjisdgjiosdjgiodsjiogsd',
            },
            'postgres': {
                'replicator_password': 'fdsiogjiaohdjkpahsiophe',
            },
        }
    else:
        server_conf['enable_remote_connections'] = True

    if high_security:
        server_conf['ssl_client_verification'] = True
        server_conf['ssl_only_connections'] = True

    if node.friendly_name in skip_bootstrap_list:
        return

    node.bootstrap(blocking=False, enter_sanity_mode=False,
                   restservice_expected=False)


def _bootstrap_manager_node(node, mgr_num, dbs, brokers, skip_bootstrap_list,
                            pre_cluster_rabbit, high_security, tempdir,
                            logger, test_config):
    node.friendly_name = 'manager' + str(mgr_num)

    _base_prep(node, tempdir)

    logger.info('Preparing manager {}'.format(node.hostname))

    if pre_cluster_rabbit:
        rabbit_nodes = {
            broker.hostname: {
                'node_id': broker.get_node_id(),
                'networks': {
                    'default': str(broker.private_ip_address)
                }
            }
            for broker in brokers
        }
    else:
        broker = brokers[0]
        rabbit_nodes = {
            broker.hostname: {
                'node_id': broker.get_node_id(),
                'networks': {
                    'default': str(broker.private_ip_address)
                }
            }
        }

    node.install_config['manager'] = {
        'private_ip': str(node.private_ip_address),
        'public_ip': str(node.private_ip_address),
        'security': {
            'admin_password': test_config['test_manager']['password'],
        },
    }
    node.install_config['rabbitmq'] = {
        'ca_path': '/tmp/ca.crt',
        'cluster_members': rabbit_nodes,
    }
    node.install_config['services_to_install'] = ['manager_service']

    if high_security:
        node.install_config['ssl_inputs'] = {
            'external_cert_path': node.remote_cert,
            'external_key_path': node.remote_key,
            'internal_cert_path': node.remote_cert,
            'internal_key_path': node.remote_key,
            'ca_cert_path': node.remote_ca,
            'external_ca_cert_path': node.remote_ca,
        }
        node.install_config['manager']['security'][
            'ssl_enabled'] = True

    if dbs:
        node.install_config['postgresql_server'] = {
            'ca_path': node.remote_ca,
            'cluster': {'nodes': {}},
        }
        node.install_config['postgresql_client'] = {
            'server_username': 'postgres',
            'server_password': dbs[0].pg_password,
        }

        if len(dbs) > 1:
            db_nodes = {
                db.hostname: {
                    'ip': str(db.private_ip_address),
                    'node_id': db.get_node_id()
                }
                for db in dbs
                if db.friendly_name not in skip_bootstrap_list
            }
            node.install_config['postgresql_server']['cluster'][
                'nodes'] = db_nodes
        else:
            node.install_config['postgresql_client'][
                'host'] = str(dbs[0].private_ip_address)

        if high_security:
            node.install_config['postgresql_client'][
                'ssl_client_verification'] = True
            node.install_config['postgresql_client']['ssl_enabled'] = True
            node.install_config['ssl_inputs'][
                'postgresql_client_cert_path'] = node.remote_cert
            node.install_config['ssl_inputs'][
                'postgresql_client_key_path'] = node.remote_key
    else:
        # If we're installing no db nodes we must put the db on the
        # manager (this only makes sense for testing external rabbit)
        node.install_config['services_to_install'].append('database_service')

    if node.friendly_name in skip_bootstrap_list:
        return

    # We have to block on every manager
    # And we can't do a cfy.use on the manager because of the ssl
    node.bootstrap(blocking=True, restservice_expected=False)

    # Correctly configure the rest client for the node
    node.client = util.create_rest_client(
        str(node.ip_address),
        username=test_config['test_manager']['username'],
        password=test_config['test_manager']['password'],
        tenant=test_config['test_manager']['tenant'],
        api_version=node.api_version,
        cert=node.local_ca,
        protocol='https',
    )


def _configure_status_reporters(managers, brokers, dbs, skip_bootstrap_list,
                                logger):
    logger.info('Configuring status reporters')
    reporters_tokens = json.loads(
        managers[0].run_command(
            # We pipe through cat to get rid of unhelpful shell escape
            # characters that cfy adds
            'cfy_manager status-reporter get-tokens --json 2>/dev/null | cat'
        ).stdout
    )
    managers_ip = ' '.join([manager.private_ip_address
                            for manager in managers])

    for broker in brokers:
        if broker.friendly_name in skip_bootstrap_list:
            continue
        _configure_status_reporter(
            broker, managers_ip, reporters_tokens['broker_status_reporter']
        )

    if len(dbs) > 1:
        for db in dbs:
            if db.friendly_name in skip_bootstrap_list:
                continue
            _configure_status_reporter(db,
                                       managers_ip,
                                       reporters_tokens['db_status_reporter'])


def _bootstrap_lb_node(node, managers, tempdir, logger):
    node.friendly_name = 'haproxy'
    _base_prep(node, tempdir)
    logger.info('Preparing load balancer {}'.format(node.hostname))

    # install haproxy and import certs
    install_sh = """yum install -y haproxy
    cat {cert} {key} > /tmp/cert.pem\n       mv /tmp/cert.pem /etc/haproxy
    chown haproxy. /etc/haproxy/cert.pem\n   chmod 400 /etc/haproxy/cert.pem
    cp {ca} /etc/haproxy\n                   chown haproxy. /etc/haproxy/ca.crt
    restorecon /etc/haproxy/*""".format(
        cert=node.remote_cert, key=node.remote_key, ca=node.remote_ca)
    node.run_command('echo "{}" > /tmp/haproxy_install.sh'.format(install_sh))
    node.run_command('chmod 700 /tmp/haproxy_install.sh')
    node.run_command('sudo /tmp/haproxy_install.sh')

    # configure haproxy
    template = Environment(
        loader=FileSystemLoader(CONFIG_DIR)).get_template('haproxy.cfg')
    config = template.render(managers=managers)
    config_path = '/etc/haproxy/haproxy.cfg'
    node.put_remote_file_content(config_path, config)
    node.run_command('sudo chown root. {}'.format(config_path))
    node.run_command('sudo chmod 644 {}'.format(config_path))
    node.run_command('sudo restorecon {}'.format(config_path))

    node.run_command('sudo systemctl enable haproxy')
    node.run_command('sudo systemctl restart haproxy')


def _configure_status_reporter(node, managers_ip, token):
    node.run_command(
        'cfy_manager status-reporter configure --managers-ip {0} '
        '--token {1} --ca-path {2}'.format(managers_ip, token, node.remote_ca)
    )
