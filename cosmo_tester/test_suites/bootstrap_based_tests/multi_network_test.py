########
# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
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

import time
import pytest
from copy import deepcopy

from cosmo_tester.framework.test_hosts import TestHosts as Hosts
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework import util
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    download_snapshot,
    restore_snapshot,
    stop_manager,
    upgrade_agents,
    upload_snapshot,
    wait_for_restore,
)

ATTRIBUTES = util.get_attributes()
POST_BOOTSTRAP_NET = 'network_3'


@pytest.fixture(scope='module')
def managers_and_vms(cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps 2 cloudify managers on a VM in rackspace OpenStack.
    Also provides VMs for testing, on separate networks.
    """

    hosts = Hosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=5,
        flavor=attributes.medium_flavor_name,
        bootstrappable=True,
        multi_net=True,
        vm_net_mappings={2: 1, 3: 2, 4: 3},
    )

    for inst in [2, 3, 4]:
        hosts.instances[inst].upload_files = False
        hosts.instances[inst].image_name = ATTRIBUTES['centos_7_image_name']
        hosts.instances[inst].linux_username = ATTRIBUTES['centos_7_username']

    try:
        hosts.create()
        prepare_managers(hosts.instances[:2], logger)
        yield hosts.instances
    finally:
        hosts.destroy()


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
def examples(managers_and_vms, ssh_key, tmpdir, attributes, logger):
    manager = managers_and_vms[0]
    vms = managers_and_vms[2:]

    examples = []
    for idx, vm in enumerate(vms, 1):
        examples.append(
            get_example_deployment(
                manager, ssh_key, logger, 'multi_net_{}'.format(idx), vm)
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
                           cfy,
                           logger,
                           tmpdir,
                           attributes):

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

    create_snapshot(old_manager, snapshot_id, attributes, logger)
    download_snapshot(old_manager, local_snapshot_path, snapshot_id, logger)

    new_manager.use()

    upload_snapshot(new_manager, local_snapshot_path, snapshot_id, logger)
    restore_snapshot(new_manager, snapshot_id, cfy, logger,
                     change_manager_password=False,
                     wait_for_post_restore_commands=False)

    wait_for_restore(new_manager, logger)

    upgrade_agents(cfy, new_manager, logger)
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
    with manager.ssh() as fabric_ssh:
        fabric_ssh.sudo(
            "{cfy_manager} add-networks --networks '{networks}' ".format(
                cfy_manager="/usr/bin/cfy_manager",
                networks=networks_json
            )
        )
        if restart:
            logger.info('Restarting services...')
            fabric_ssh.sudo('systemctl restart cloudify-rabbitmq')
            fabric_ssh.sudo('systemctl restart nginx')
            fabric_ssh.sudo('systemctl restart cloudify-mgmtworker')


@pytest.fixture(scope='function')
def proxy_hosts(request, cfy, ssh_key, module_tmpdir, attributes, logger):
    hosts = Hosts(
        cfy, ssh_key, module_tmpdir, attributes, logger, 3,
        bootstrappable=True,)
    proxy, manager, vm = hosts.instances

    proxy.upload_files = False
    proxy.image_name = ATTRIBUTES['centos_7_image_name']
    vm.upload_files = False
    vm.image_name = ATTRIBUTES['centos_7_image_name']

    try:
        hosts.create()
        proxy_prepare_hosts(hosts.instances, logger)
        yield hosts.instances
    finally:
        hosts.destroy()


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
    with proxy.ssh() as fabric:
        fabric.sudo('yum install socat -y')
        for port in [5671, 53333]:
            service = 'proxy_{0}'.format(port)
            filename = '/usr/lib/systemd/system/{0}.service'.format(service)
            logger.info('Deploying proxy service file')
            proxy.put_remote_file_content(
                filename,
                PROXY_SERVICE_TEMPLATE.format(
                    ip=manager_ip, port=port),
            )
            logger.info('Enabling proxy service')
            fabric.sudo('systemctl enable {0}'.format(service))
            logger.info('Starting proxy service')
            fabric.sudo('systemctl start {0}'.format(service))

    logger.info('Bootstrapping manager...')
    manager.wait_for_ssh()
    manager.bootstrap(blocking=True, upload_license=True)


def test_agent_via_proxy(proxy_hosts,
                         logger,
                         ssh_key):
    proxy, manager, vm = proxy_hosts

    # to make sure that the agents go through the proxy, and not connect to
    # the manager directly, we block all communication on the manager's
    # rabbitmq and internal REST endpoint, except from the proxy (and from
    # localhost)
    manager_ip = manager.private_ip_address
    proxy_ip = proxy.private_ip_address
    with manager.ssh() as fabric:
        for port in [5671, 53333]:
            fabric.sudo(
                'iptables -I INPUT -p tcp -s 0.0.0.0/0 --dport {0} -j DROP'
                .format(port))
            for ip in [proxy_ip, manager_ip, '127.0.0.1']:
                fabric.sudo(
                    'iptables -I INPUT -p tcp -s {0} --dport {1} -j ACCEPT'
                    .format(ip, port))

    manager.use()

    example = get_example_deployment(
        manager, ssh_key, logger, 'agent_via_proxy', vm)
    example.upload_and_verify_install()
    example.uninstall()
