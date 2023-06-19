import time
import pytest
from copy import deepcopy

from cosmo_tester.framework.test_hosts import Hosts, VM
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.snapshots import (
    create_copy_and_restore_snapshot,
    stop_manager,
    upgrade_agents,
)

POST_BOOTSTRAP_NET = 'network_3'


@pytest.fixture(scope='function')
def managers_and_vms(ssh_key, module_tmpdir, test_config, logger,
                     request):
    """Bootstraps 2 cloudify managers on a VM in rackspace OpenStack.
    Also provides VMs for testing, on separate networks.
    """

    hosts = Hosts(
        ssh_key, module_tmpdir, test_config, logger, request,
        number_of_instances=5,
        bootstrappable=True,
        multi_net=True,
        vm_net_mappings={2: 1, 3: 2, 4: 3},
    )

    for inst in [2, 3, 4]:
        hosts.instances[inst] = VM('rhel_8', test_config)

    passed = True

    try:
        hosts.create()
        prepare_managers(hosts.instances[:2], logger)
        yield hosts.instances
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)


def prepare_managers(managers, logger):
    # The preconfigure callback populates the networks config prior to the BS
    for instance in managers:
        # Remove one of the networks - it will be added post-bootstrap
        all_networks = deepcopy(instance.networks)
        all_networks.pop(POST_BOOTSTRAP_NET)

        instance.install_config['networks'] = all_networks

        # Wait for ssh before enable the nics
        instance.wait_for_ssh()
        # Configure NICs in order for networking to work properly
        instance.enable_nics()

        instance.bootstrap(blocking=False, upload_license=True)

    for instance in managers:
        logger.info('Waiting for bootstrap of {}'.format(instance.server_id))
        while not instance.bootstrap_is_complete():
            time.sleep(3)


@pytest.fixture(scope='function')
def examples(managers_and_vms, ssh_key, tmpdir, logger, test_config):
    manager = managers_and_vms[0]
    vms = managers_and_vms[2:]

    examples = []
    for idx, vm in enumerate(vms, 1):
        examples.append(
            get_example_deployment(
                manager, ssh_key, logger, 'multi_net_{}'.format(idx),
                test_config, vm, suffix=str(idx))
        )
        examples[-1].inputs['network'] = 'network_{}'.format(idx)

    try:
        yield examples
    finally:
        for example in examples:
            if example.installed:
                example.uninstall()


def test_multiple_networks(managers_and_vms,
                           examples,
                           logger,
                           tmpdir,
                           test_config):

    logger.info('Testing managers with multiple networks')

    # We should have at least 3 hello world objects. We will verify the first
    # one completely on the first manager.
    # All the other ones will be installed on the first manager,
    # then we'll create a snapshot and restore it on the second manager, and
    # finally, to complete the verification, we'll uninstall the remaining
    # hellos on the new manager

    old_manager, new_manager = managers_and_vms[:2]
    snapshot_id = 'multi_net_test_snapshot'
    local_snapshot_path = str(tmpdir / 'snap.zip')

    # One multi-net dep will be used to test a network added post bootstrap
    logger.info('Selecting post-bootstrap network test vm')
    post_bootstrap_example_idx = None
    for idx, example in enumerate(examples):
        if example.inputs['network'] == POST_BOOTSTRAP_NET:
            post_bootstrap_example_idx = idx
    assert post_bootstrap_example_idx is not None
    post_bootstrap_example = examples.pop(post_bootstrap_example_idx)
    post_bootstrap_example.manager = new_manager

    for example in examples:
        example.upload_and_verify_install()

    create_copy_and_restore_snapshot(
        old_manager, new_manager, snapshot_id, local_snapshot_path, logger,
        wait_for_post_restore_commands=False)

    upgrade_agents(new_manager, logger, test_config)
    stop_manager(old_manager, logger)

    for example in examples:
        example.manager = new_manager
        example.uninstall()

    _add_new_network(new_manager, logger)
    post_bootstrap_example.upload_and_verify_install()
    post_bootstrap_example.uninstall()


def _add_new_network(manager, logger, restart=True):
    logger.info('Adding network `{0}` to the new manager'.format(
        POST_BOOTSTRAP_NET))

    old_networks = deepcopy(manager.networks)
    new_network_ip = old_networks.pop(POST_BOOTSTRAP_NET)
    networks_json = (
        '{{ "{0}": "{1}" }}'
    ).format(POST_BOOTSTRAP_NET, new_network_ip)
    manager.run_command(
        "{cfy_manager} add-networks --networks '{networks}' ".format(
            cfy_manager="/usr/bin/cfy_manager",
            networks=networks_json
        ),
        use_sudo=True,
    )
    if restart:
        logger.info('Restarting services...')
        manager.run_command('supervisorctl restart cloudify-rabbitmq',
                            use_sudo=True)
        manager.run_command('supervisorctl restart nginx', use_sudo=True)
        manager.run_command('supervisorctl restart cloudify-mgmtworker',
                            use_sudo=True)


@pytest.fixture(scope='function')
def proxy_hosts(request, ssh_key, module_tmpdir, test_config, logger):
    hosts = Hosts(
        ssh_key, module_tmpdir, test_config, logger, request, 3,
        bootstrappable=True,)
    hosts.instances[0] = VM('rhel_8', test_config)
    hosts.instances[2] = VM('rhel_8', test_config)
    proxy, manager, vm = hosts.instances

    passed = True

    try:
        hosts.create()
        proxy_prepare_hosts(hosts.instances, logger)
        yield hosts.instances
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)


PROXY_SERVICE_TEMPLATE = """
[Unit]
Description=Proxy for port {port}
Wants=network-online.target
[Service]
User=root
Group=root
ExecStart=/bin/socat TCP-LISTEN:{port},fork TCP:{ip}:{port}
Restart=always
RestartSec=20s
[Install]
WantedBy=multi-user.target
"""


def proxy_prepare_hosts(instances, logger):
    proxy, manager, vm = instances
    proxy_ip = proxy.private_ip_address
    manager_ip = manager.private_ip_address
    # on the manager, we override the default network ip, so that by default
    # all agents will go through the proxy
    manager.install_config['networks'] = {
        'default': str(proxy_ip),
        # Included so the cert contains this IP for mgmtworker
        'manager_private': str(manager_ip),
    }

    # setup the proxy - simple socat services that forward all TCP connections
    # to the manager
    proxy.run_command('yum install socat -y', use_sudo=True)
    for port in [443, 5671, 53333, 15671]:
        service = 'proxy_{0}'.format(port)
        filename = '/usr/lib/systemd/system/{0}.service'.format(service)
        logger.info('Deploying proxy service file')
        proxy.put_remote_file_content(
            filename,
            PROXY_SERVICE_TEMPLATE.format(
                ip=manager_ip, port=port),
        )
        logger.info('Enabling proxy service')
        proxy.run_command('systemctl enable {0}'.format(service),
                          use_sudo=True)
        logger.info('Starting proxy service')
        proxy.run_command('systemctl start {0}'.format(service),
                          use_sudo=True)

    logger.info('Bootstrapping manager...')
    manager.wait_for_ssh()
    manager.bootstrap(blocking=True, upload_license=True)


def test_agent_via_proxy(proxy_hosts,
                         logger,
                         ssh_key,
                         test_config):
    proxy, manager, vm = proxy_hosts

    # to make sure that the agents go through the proxy, and not connect to
    # the manager directly, we block all communication on the manager's
    # rabbitmq and internal REST endpoint, except from the proxy (and from
    # localhost)
    manager_ip = manager.private_ip_address
    proxy_ip = proxy.private_ip_address
    for port in [5671, 53333]:
        manager.run_command(
            'iptables -I INPUT -p tcp -s 0.0.0.0/0 --dport {0} -j DROP'
            .format(port), use_sudo=True)
        for ip in [proxy_ip, manager_ip, '127.0.0.1']:
            manager.run_command(
                'iptables -I INPUT -p tcp -s {0} --dport {1} -j ACCEPT'
                .format(ip, port), use_sudo=True)

    example = get_example_deployment(
        manager, ssh_key, logger, 'agent_via_proxy', test_config, vm)
    example.upload_and_verify_install()
    example.uninstall()
