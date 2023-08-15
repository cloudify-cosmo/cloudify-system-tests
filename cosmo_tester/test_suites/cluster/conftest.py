import os
import time

from os.path import join, dirname
import pytest

from cosmo_tester.framework.test_hosts import Hosts
from cosmo_tester.framework import util
from .cfy_cluster_manager_shared import REMOTE_CLUSTER_CONFIG_PATH

CONFIG_DIR = join(dirname(__file__), 'config')


class InsufficientVmsError(Exception):
    pass


def skip(*args, **kwargs):
    return True


@pytest.fixture(scope='session')
def three_session_vms(request, ssh_key, session_tmpdir, test_config,
                      session_logger):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True,
                  number_of_instances=3)
    try:
        hosts.create()
        if len(request.session.items) > 1:
            hosts.rsync_backup()
        yield hosts.instances
    finally:
        hosts.destroy()


@pytest.fixture(scope='session')
def three_session_vms_fqdns(request, ssh_key, session_tmpdir, test_config,
                            session_logger):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True,
                  number_of_instances=3)
    try:
        hosts.create(use_fqdn=True)
        if len(request.session.items) > 1:
            hosts.rsync_backup()
        yield hosts.instances
    finally:
        hosts.destroy()


@pytest.fixture(scope='session')
def three_ipv6_session_vms(request, ssh_key, session_tmpdir, test_config,
                           session_logger):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True,
                  number_of_instances=3, ipv6_net=True)
    try:
        hosts.create()
        if len(request.session.items) > 1:
            hosts.rsync_backup()
        yield hosts.instances
    finally:
        hosts.destroy()


@pytest.fixture(scope='session')
def four_session_vms(request, ssh_key, session_tmpdir, test_config,
                     session_logger):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True,
                  number_of_instances=4)
    try:
        hosts.create()
        if len(request.session.items) > 1:
            hosts.rsync_backup()
        yield hosts.instances
    finally:
        hosts.destroy()


@pytest.fixture(scope='session')
def six_session_vms(request, ssh_key, session_tmpdir, test_config,
                    session_logger):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True,
                  number_of_instances=6)
    try:
        hosts.create()
        if len(request.session.items) > 1:
            hosts.rsync_backup()
        yield hosts.instances
    finally:
        hosts.destroy()


@pytest.fixture(scope='session')
def nine_session_vms(request, ssh_key, session_tmpdir, test_config,
                     session_logger):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True,
                  number_of_instances=9)
    try:
        hosts.create()
        if len(request.session.items) > 1:
            hosts.rsync_backup()
        yield hosts.instances
    finally:
        hosts.destroy()


@pytest.fixture(scope='session')
def nine_session_vms_fqdns(request, ssh_key, session_tmpdir, test_config,
                           session_logger):
    hosts = Hosts(ssh_key, session_tmpdir, test_config,
                  session_logger, request, bootstrappable=True,
                  number_of_instances=9)
    try:
        hosts.create(use_fqdn=True)
        if len(request.session.items) > 1:
            hosts.rsync_backup()
        yield hosts.instances
    finally:
        hosts.destroy()


@pytest.fixture(scope='function')
def brokers(three_session_vms, test_config, logger, request):
    util.reboot_if_required(three_session_vms)
    for vm in three_session_vms:
        _ensure_installer_installed(vm)
    yield _get_hosts(three_session_vms, test_config, logger,
                     broker_count=3)
    if len(request.session.items) > 1:
        util.rsync_restore(three_session_vms)


@pytest.fixture(scope='function')
def broker(session_manager, test_config, logger, request):
    util.reboot_if_required([session_manager])
    _brokers = _get_hosts([session_manager], test_config, logger,
                          broker_count=1)
    yield _brokers[0]
    if len(request.session.items) > 1:
        util.rsync_restore([session_manager])


@pytest.fixture(scope='function')
def dbs(three_session_vms, test_config, logger, request):
    util.reboot_if_required(three_session_vms)
    for vm in three_session_vms:
        _ensure_installer_installed(vm)
    yield _get_hosts(three_session_vms, test_config, logger,
                     db_count=3)
    if len(request.session.items) > 1:
        util.rsync_restore(three_session_vms)


@pytest.fixture(scope='function')
def brokers_and_manager(three_session_vms, test_config, logger, request):
    util.reboot_if_required(three_session_vms)
    for vm in three_session_vms:
        _ensure_installer_installed(vm)
    yield _get_hosts(three_session_vms, test_config, logger,
                     broker_count=2, manager_count=1)
    if len(request.session.items) > 1:
        util.rsync_restore(three_session_vms)


@pytest.fixture(scope='function')
def brokers3_and_manager(four_session_vms, test_config, logger, request):
    util.reboot_if_required(four_session_vms)
    yield _get_hosts(four_session_vms, test_config, logger,
                     broker_count=3, manager_count=1)
    if len(request.session.items) > 1:
        util.rsync_restore(four_session_vms)


@pytest.fixture(scope='function')
def full_cluster_ips(nine_session_vms, test_config, logger, request):
    util.reboot_if_required(nine_session_vms)
    for vm in nine_session_vms:
        _ensure_installer_installed(vm)
    yield _get_hosts(nine_session_vms, test_config, logger,
                     broker_count=3, db_count=3, manager_count=3,
                     pre_cluster_rabbit=True)
    if len(request.session.items) > 1:
        util.rsync_restore(nine_session_vms)


@pytest.fixture(scope='function')
def full_cluster_names(nine_session_vms, test_config, logger, request):
    util.reboot_if_required(nine_session_vms)
    for vm in nine_session_vms:
        _ensure_installer_installed(vm)
    yield _get_hosts(nine_session_vms, test_config, logger,
                     broker_count=3, db_count=3, manager_count=3,
                     pre_cluster_rabbit=True, use_hostnames=True)
    if len(request.session.items) > 1:
        util.rsync_restore(nine_session_vms)


@pytest.fixture(scope='function')
def cluster_missing_one_db(nine_session_vms, test_config, logger, request):
    util.reboot_if_required(nine_session_vms)
    for vm in nine_session_vms:
        _ensure_installer_installed(vm)
    yield _get_hosts(nine_session_vms, test_config, logger,
                     broker_count=3, db_count=3, manager_count=3,
                     skip_bootstrap_list=['db3'],
                     pre_cluster_rabbit=True)
    if len(request.session.items) > 1:
        util.rsync_restore(nine_session_vms)


@pytest.fixture(scope='function')
def cluster_with_single_db(six_session_vms, test_config, logger, request):
    util.reboot_if_required(six_session_vms)
    yield _get_hosts(six_session_vms, test_config, logger,
                     broker_count=3, db_count=1, manager_count=2,
                     pre_cluster_rabbit=True)
    if len(request.session.items) > 1:
        util.rsync_restore(six_session_vms)


@pytest.fixture(scope='function')
def minimal_cluster(four_session_vms, test_config, logger, request):
    util.reboot_if_required(four_session_vms)
    yield _get_hosts(four_session_vms, test_config, logger,
                     broker_count=1, db_count=1, manager_count=2,
                     pre_cluster_rabbit=True)
    if len(request.session.items) > 1:
        util.rsync_restore(four_session_vms)


@pytest.fixture(scope='function')
def three_nodes_cluster(three_session_vms, test_config, logger, request):
    util.reboot_if_required(three_session_vms)
    for vm in three_session_vms:
        _ensure_installer_installed(vm)
    yield _get_hosts(three_session_vms, test_config, logger,
                     pre_cluster_rabbit=True, three_nodes_cluster=True)
    if len(request.session.items) > 1:
        util.rsync_restore(three_session_vms)


@pytest.fixture(scope='function')
def three_nodes_ipv6_cluster(three_ipv6_session_vms, test_config, logger,
                             request):
    util.reboot_if_required(three_ipv6_session_vms)
    for vm in three_ipv6_session_vms:
        _ensure_installer_installed(vm)
    yield _get_hosts(three_ipv6_session_vms, test_config, logger,
                     pre_cluster_rabbit=True, three_nodes_cluster=True)
    if len(request.session.items) > 1:
        util.rsync_restore(three_ipv6_session_vms)


@pytest.fixture(scope='function')
def three_vms(three_session_vms, test_config, logger, request):
    util.reboot_if_required(three_session_vms)
    for vm in three_session_vms:
        _ensure_installer_not_installed(vm)
    yield _get_hosts(three_session_vms, test_config, logger,
                     three_nodes_cluster=True, bootstrap=False)
    if len(request.session.items) > 1:
        util.rsync_restore(three_session_vms)


@pytest.fixture(scope='function')
def three_vms_fqdns(three_session_vms_fqdns, test_config, logger, request):
    util.reboot_if_required(three_session_vms_fqdns)
    for vm in three_session_vms_fqdns:
        _ensure_installer_not_installed(vm)
    yield _get_hosts(three_session_vms_fqdns, test_config, logger,
                     three_nodes_cluster=True, bootstrap=False)
    if len(request.session.items) > 1:
        util.rsync_restore(three_session_vms_fqdns)


@pytest.fixture(scope='function')
def three_vms_ipv6(three_ipv6_session_vms, test_config, logger, request):
    util.reboot_if_required(three_ipv6_session_vms)
    for vm in three_nodes_ipv6_cluster:
        _ensure_installer_not_installed(vm)
    yield _get_hosts(three_ipv6_session_vms, test_config, logger,
                     three_nodes_cluster=True, bootstrap=False)
    if len(request.session.items) > 1:
        util.rsync_restore(three_ipv6_session_vms)


@pytest.fixture(scope='function')
def nine_vms(nine_session_vms, test_config, logger, request):
    util.reboot_if_required(nine_session_vms)
    for vm in nine_session_vms:
        _ensure_installer_not_installed(vm)
    yield _get_hosts(nine_session_vms, test_config, logger,
                     broker_count=3, db_count=3,
                     manager_count=3, bootstrap=False)
    if len(request.session.items) > 1:
        util.rsync_restore(nine_session_vms)


@pytest.fixture(scope='function')
def nine_vms_fqdns(nine_session_vms_fqdns, test_config, logger, request):
    util.reboot_if_required(nine_session_vms_fqdns)
    for vm in nine_session_vms_fqdns:
        _ensure_installer_not_installed(vm)
    yield _get_hosts(nine_session_vms_fqdns, test_config, logger,
                     broker_count=3, db_count=3,
                     manager_count=3, bootstrap=False)
    if len(request.session.items) > 1:
        util.rsync_restore(nine_session_vms_fqdns)


def _ensure_installer_not_installed(vm):
    vm.wait_for_ssh()
    vm.run_command(
        'if rpm -qi cloudify-manager-install; then '
        # yum clean all doesn't clean all, so let's be more forceful
        'sudo rm -rf /var/cache/yum ; '
        'sudo yum remove -y cloudify-manager-install {}; '
        'sudo rm -rf /opt/manager /var/log/cloudify; fi'.format(
            # We need to remove the other components as well or we end up with
            # failures when installing older clusters in the upgrade tests
            ' '.join([
                'cloudify-agents',
                'cloudify-cli',
                'cloudify-composer',
                'cloudify-management-worker',
                'cloudify-premium',
                'cloudify-rabbitmq',
                'cloudify-rest-service',
                'cloudify-stage',
                'erlang',
                'etcd',
                'nginx',
                'node_exporter',
                'nodejs',
                'patroni',
                'postgres_exporter',
                'postgresql95',
                'postgresql95-contrib',
                'postgresql95-devel',
                'postgresql95-libs',
                'postgresql95-server',
                'prometheus',
                'python-psycopg2',
                'rabbitmq-server',
            ]),
        )
    )


def _ensure_installer_installed(vm):
    vm.wait_for_ssh()
    vm.run_command(
        # yum clean all doesn't clean all, so let's be more forceful
        'sudo rm -rf /var/cache/yum '
        '&& (rpm -qi cloudify-manager-install '
        '|| sudo yum install -y cloudify-manager-install.rpm)'
    )


def _get_hosts(instances, test_config, logger,
               broker_count=0, manager_count=0, db_count=0,
               skip_bootstrap_list=None,
               # Pre-cluster rabbit determines whether to cluster rabbit
               # during the bootstrap.
               # High security will pre-set all certs (not just required ones)
               # and use postgres client certs.
               pre_cluster_rabbit=False, high_security=True, extra_node=False,
               use_hostnames=False, three_nodes_cluster=False,
               bootstrap=True):
    number_of_cluster_instances = (
        3 if three_nodes_cluster else broker_count + db_count + manager_count)
    has_extra_node = (1 if extra_node else 0)
    number_of_instances = number_of_cluster_instances + has_extra_node
    if skip_bootstrap_list is None:
        skip_bootstrap_list = []

    cluster_password = util.generate_password()

    if len(instances) != number_of_instances:
        raise InsufficientVmsError('Required %s instances, but got %s',
                                   number_of_instances, instances)

    tempdir = instances[0]._tmpdir_base

    if three_nodes_cluster:
        name_mappings = ['cloudify-1', 'cloudify-2', 'cloudify-3']
    else:
        name_mappings = ['rabbit-{}'.format(i)
                         for i in range(broker_count)]
        name_mappings.extend([
            'db-{}'.format(i) for i in range(db_count)
        ])
        name_mappings.extend([
            'manager-{}'.format(i) for i in range(manager_count)
        ])
    if has_extra_node:
        name_mappings.append('extra_node')

    for idx, node in enumerate(instances):
        node.wait_for_ssh()
        # This needs to happen before we start bootstrapping nodes
        # because the hostname is used by nodes that are being
        # bootstrapped with reference to nodes that may not have been
        # bootstrapped yet.
        node.hostname = name_mappings[idx]
        node.run_command('sudo hostnamectl set-hostname {}'.format(
            name_mappings[idx]
        ))
        if node.is_manager:
            for inst_config in node.basic_install_config, node.install_config:
                inst_config.setdefault(
                    'manager', {}).setdefault(
                    'security', {})['admin_password'] = cluster_password
                # Without this, comparing managers listed by cluster status
                # will fail because they will have the actual VM hostnames
                inst_config['manager']['hostname'] = node.hostname

    if use_hostnames:
        hosts_entries = ['\n# Added for hostname test']
        hosts_entries.extend(
            '{ip} {name}'.format(ip=node.private_ip_address,
                                 name=node.hostname)
            for node in instances
        )
        hosts_entries = '\n'.join(hosts_entries)
        for node in instances:
            if not hasattr(node, 'install_config'):
                # This is a load balancer or other non-cloudify node
                continue
            node.install_config['manager']['private_ip'] = node.hostname
            node.run_command(
               "echo '{hosts}' | sudo tee -a /etc/hosts".format(
                   hosts=hosts_entries,
               )
            )
    else:
        for node in instances:
            if not hasattr(node, 'install_config'):
                # This is a load balancer or other non-cloudify node
                continue
            node.install_config['manager'][
                'private_ip'] = node.private_ip_address

    if three_nodes_cluster:
        brokers = dbs = managers = instances[:3]
    else:
        brokers = instances[:broker_count]
        dbs = instances[broker_count:broker_count + db_count]
        managers = instances[broker_count + db_count:
                             broker_count + db_count + manager_count]

    if bootstrap:
        run_cluster_bootstrap(dbs, brokers, managers, skip_bootstrap_list,
                              pre_cluster_rabbit, high_security,
                              use_hostnames, tempdir, test_config)

    logger.info('All nodes are created%s.',
                ' and bootstrapped' if bootstrap else '')

    return instances


def run_cluster_bootstrap(dbs, brokers, managers, skip_bootstrap_list,
                          pre_cluster_rabbit, high_security, use_hostnames,
                          tempdir, test_config, credentials=None):
    for node_num, node in enumerate(brokers, start=1):
        _bootstrap_rabbit_node(node, node_num, brokers,
                               skip_bootstrap_list, pre_cluster_rabbit,
                               tempdir, use_hostnames, credentials)

    for node_num, node in enumerate(dbs, start=1):
        _bootstrap_db_node(node, node_num, dbs, skip_bootstrap_list,
                           high_security, tempdir,
                           use_hostnames, credentials)

    # Ensure all backend nodes are up before installing managers
    for node in brokers + dbs:
        if node.friendly_name in skip_bootstrap_list:
            continue
        while not node.bootstrap_is_complete():
            node.log_action('Checking bootstrap state')
            time.sleep(5)

    for node_num, node in enumerate(managers, start=1):
        _bootstrap_manager_node(node, node_num, dbs, brokers,
                                skip_bootstrap_list,
                                pre_cluster_rabbit, high_security,
                                tempdir, test_config,
                                use_hostnames, credentials)


def _base_prep(node, tempdir):
    node.run_command(
        'mkdir -p /tmp/bs_logs'
    )

    node.run_command(
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
        tempdir,
        node_cert,
        node_key,
        ca_cert,
        ca_key,
    )

    db_client_cert = cert_base.format(node_friendly_name='cloudify',
                                      extension='crt')
    db_client_key = cert_base.format(node_friendly_name='cloudify',
                                     extension='key')

    # In case we're using postgres client auth we need a CN of cloudify
    util.generate_ssl_certificate(
        [],
        'cloudify',
        tempdir,
        db_client_cert,
        db_client_key,
        ca_cert,
        ca_key,
    )

    db_su_cert = cert_base.format(node_friendly_name='postgres',
                                  extension='crt')
    db_su_key = cert_base.format(node_friendly_name='postgres',
                                 extension='key')

    # In case we're using postgres client auth we need a CN of cloudify
    util.generate_ssl_certificate(
        [],
        'postgres',
        tempdir,
        db_su_cert,
        db_su_key,
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
        local_path=db_client_cert,
        remote_path='/tmp/db_client.crt',
    )
    node.put_remote_file(
        local_path=db_client_key,
        remote_path='/tmp/db_client.key',
    )
    node.put_remote_file(
        local_path=db_su_cert,
        remote_path='/tmp/db_su.crt',
    )
    node.put_remote_file(
        local_path=db_su_key,
        remote_path='/tmp/db_su.key',
    )
    node.put_remote_file(
        local_path=ca_cert,
        remote_path=remote_ca,
    )

    node.local_cert = node_cert
    node.remote_cert = remote_cert
    node.local_key = node_key
    node.remote_key = remote_key
    node.api_ca_path = ca_cert
    node.remote_ca = remote_ca


def _bootstrap_rabbit_node(node, rabbit_num, brokers, skip_bootstrap_list,
                           pre_cluster_rabbit, tempdir,
                           use_hostnames, credentials=None):
    node.friendly_name = 'rabbit' + str(rabbit_num)

    _base_prep(node, tempdir)

    node.log_action('Preparing rabbit')

    join_target = ''
    if pre_cluster_rabbit and rabbit_num != 1:
        join_target = brokers[0].hostname

    if pre_cluster_rabbit:
        rabbit_nodes = {
            broker.hostname: {
                'networks': {
                    'default': (
                        broker.hostname if use_hostnames else
                        str(broker.private_ip_address)
                    )
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

    _add_monitoring_config(node)

    if credentials:
        util.update_dictionary(node.install_config, credentials)

    if pre_cluster_rabbit and rabbit_num == 1:
        node.bootstrap(blocking=True, restservice_expected=False,
                       config_name='rabbit')
    else:
        node.bootstrap(blocking=False, restservice_expected=False,
                       config_name='rabbit')


def _bootstrap_db_node(node, db_num, dbs, skip_bootstrap_list, high_security,
                       tempdir, use_hostnames, credentials=None):
    node.friendly_name = 'db' + str(db_num)

    _base_prep(node, tempdir)

    node.log_action('Preparing DB')

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
        db_nodes = {
            db.hostname: {
                'ip': (
                    db.hostname if use_hostnames else
                    str(db.private_ip_address)
                )
            }
            for db in dbs
        }
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

    _add_monitoring_config(node)

    if credentials:
        util.update_dictionary(node.install_config, credentials)

    node.bootstrap(blocking=False, restservice_expected=False,
                   config_name='db')


def _bootstrap_manager_node(node, mgr_num, dbs, brokers, skip_bootstrap_list,
                            pre_cluster_rabbit, high_security, tempdir,
                            test_config, use_hostnames, credentials=None):
    node.friendly_name = 'manager' + str(mgr_num)

    _base_prep(node, tempdir)

    node.log_action('Preparing manager')

    if pre_cluster_rabbit:
        rabbit_nodes = {
            broker.hostname: {
                'networks': {
                    'default': (
                        broker.hostname if use_hostnames else
                        str(broker.private_ip_address)
                    )
                }
            }
            for broker in brokers
        }
    else:
        broker = brokers[0]
        rabbit_nodes = {
            broker.hostname: {
                'networks': {
                    'default': (
                        broker.hostname if use_hostnames else
                        str(broker.private_ip_address)
                    )
                }
            }
        }

    node.install_config['manager']['private_ip'] = \
        str(node.private_ip_address)
    node.install_config['manager']['public_ip'] = \
        str(node.ip_address)
    node.install_config['rabbitmq'] = {
        'ca_path': '/tmp/ca.crt',
        'cluster_members': rabbit_nodes,
    }
    node.install_config['services_to_install'] = ['manager_service',
                                                  'entropy_service']

    if high_security:
        node.install_config['ssl_inputs'] = {
            'internal_cert_path': node.remote_cert,
            'internal_key_path': node.remote_key,
            'ca_cert_path': node.remote_ca,
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
                    'ip': (
                        db.hostname if use_hostnames else
                        str(db.private_ip_address)
                    ),
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
                'postgresql_client_cert_path'] = '/tmp/db_client.crt'
            node.install_config['ssl_inputs'][
                'postgresql_client_key_path'] = '/tmp/db_client.key'
            node.install_config['ssl_inputs'][
                'postgresql_superuser_client_cert_path'] = '/tmp/db_su.crt'
            node.install_config['ssl_inputs'][
                'postgresql_superuser_client_key_path'] = '/tmp/db_su.key'
    else:
        # If we're installing no db nodes we must put the db on the
        # manager (this only makes sense for testing external rabbit)
        node.install_config['services_to_install'].append('database_service')

    if node.friendly_name in skip_bootstrap_list:
        return

    upload_license = mgr_num == 1

    _add_monitoring_config(node, manager=True)

    if credentials:
        util.update_dictionary(node.install_config, credentials)

    # We have to block on every manager
    node.bootstrap(blocking=True, restservice_expected=False,
                   upload_license=upload_license, config_name='manager')

    # Correctly configure the rest client for the node
    node.client = node.get_rest_client(proto='https')


def _add_monitoring_config(node, manager=False):
    """Add monitoring settings to config."""
    monitoring_user = 'friendlymonitoringuser'
    monitoring_pass = 'thisshouldbeareallystrongsecretpassword'
    config = node.install_config

    config['services_to_install'] = config.get(
        'services_to_install', []) + ['monitoring_service']
    config['prometheus'] = {
        'credentials': {
            'username': monitoring_user,
            'password': monitoring_pass,
        },
        'cert_path': node.remote_cert,
        'key_path': node.remote_key,
        'ca_path': node.remote_ca,
    }

    if manager:
        for section_name in ['rabbitmq', 'postgresql_client', 'manager']:
            section = config[section_name] = config.get(section_name, {})
            section['monitoring'] = {
                'username': monitoring_user,
                'password': monitoring_pass,
            }
            config[section_name] = section


def _remove_cluster(node):
    node.log_action('Checking for cluster manager')
    if node.run_command('which cfy_cluster_manager', warn_only=True).ok:
        node.log_action('Tearing down cluster manager using '
                        'cloudify cluster manager')
        node.run_command('sudo cfy_cluster_manager remove --config-path '
                         '{}'.format(REMOTE_CLUSTER_CONFIG_PATH))

    # yum clean all doesn't clean all, so let's be more forceful
    node.log_action('Cleaning yum cache')
    node.run_command('sudo rm -rf /var/cache/yum')

