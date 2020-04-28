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
import yaml
import pytest
from copy import deepcopy

from cloudify_cli.constants import DEFAULT_TENANT_NAME
from cosmo_tester.framework.test_hosts import (
    TestHosts as Hosts,
)
from cosmo_tester.framework.examples.hello_world import (
    HelloWorldExample,
    centos_hello_world,
)
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework import util
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    download_snapshot,
    upload_snapshot,
    restore_snapshot,
    upgrade_agents,
    stop_manager
)

ATTRIBUTES = util.get_attributes()

NETWORK_2 = "network_2"


@pytest.fixture(scope='module')
def managers(cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps 2 cloudify managers on a VM in rackspace OpenStack."""

    hosts = Hosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=2,
        flavor=attributes.medium_flavor_name,
        bootstrappable=True,
        multi_net=True,
    )

    try:
        hosts.create()
        prepare_hosts(hosts.instances, logger)
        yield hosts.instances
    finally:
        hosts.destroy()


def prepare_hosts(instances, logger):
    # The preconfigure callback populates the networks config prior to the BS
    for instance in instances:
        # Remove one of the networks - it will be added post-bootstrap
        all_networks = deepcopy(instance.networks)
        all_networks.pop(NETWORK_2)

        instance.install_config['networks'] = all_networks

        # Wait for ssh before enable the nics
        instance.wait_for_ssh()
        # Configure NICs in order for networking to work properly
        instance.enable_nics()

        instance.bootstrap(blocking=False, upload_license=True)

    for instance in instances:
        logger.info('Waiting for bootstrap of {}'.format(instance.server_id))
        while not instance.bootstrap_is_complete():
            time.sleep(3)


def test_multiple_networks(managers,
                           cfy,
                           multi_network_hello_worlds,
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

    old_manager = managers[0]
    new_manager = managers[1]
    snapshot_id = 'SNAPSHOT_ID'
    local_snapshot_path = str(tmpdir / 'snap.zip')

    # The first hello is the one that belongs to a network that will be added
    # manually post bootstrap to the new manager
    post_bootstrap_hello = multi_network_hello_worlds.pop(0)
    post_bootstrap_hello.manager = new_manager

    for hello in multi_network_hello_worlds:
        hello.upload_and_verify_install()

    create_snapshot(old_manager, snapshot_id, attributes, logger)
    download_snapshot(old_manager, local_snapshot_path, snapshot_id, logger)

    new_manager.use()

    upload_snapshot(new_manager, local_snapshot_path, snapshot_id, logger)
    restore_snapshot(new_manager, snapshot_id, cfy, logger,
                     change_manager_password=False)

    upgrade_agents(cfy, new_manager, logger)
    stop_manager(old_manager, logger)

    for hello in multi_network_hello_worlds:
        hello.manager = new_manager
        hello.uninstall()
        hello.delete_deployment()

    _add_new_network(new_manager, logger)
    post_bootstrap_hello.verify_all()


def _add_new_network(manager, logger, restart=True):
    logger.info('Adding network `{0}` to the new manager'.format(NETWORK_2))

    old_networks = deepcopy(manager.networks)
    network2_ip = old_networks.pop(NETWORK_2)
    networks_json = (
        '{{ "{0}": "{1}" }}'
    ).format(NETWORK_2, network2_ip)
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


class MultiNetworkHelloWorld(HelloWorldExample):
    def _patch_blueprint(self):
        with open(self.blueprint_path, 'r') as f:
            blueprint_dict = yaml.load(f)

        node_props = blueprint_dict['node_templates']['vm']['properties']
        agent_config = node_props['agent_config']
        agent_config['network'] = {'get_input': 'manager_network_name'}

        inputs = blueprint_dict['inputs']
        inputs['manager_network_name'] = {}

        with open(self.blueprint_path, 'w') as f:
            yaml.dump(blueprint_dict, f)


def _make_network_hello_worlds(cfy, managers, attributes, ssh_key, tmpdir,
                               logger):
    # The first manager is the initial one
    manager = managers[0]
    manager.use()
    hellos = []

    # Add a MultiNetworkHelloWorld per management network
    for network_name, network_id in attributes.network_names.iteritems():
        tenant = util.prepare_and_get_test_tenant(
            '{0}_tenant'.format(network_name), manager, cfy
        )
        hello = MultiNetworkHelloWorld(
            cfy, manager, attributes, ssh_key, logger, tmpdir,
            tenant=tenant, suffix=network_name)
        hello.blueprint_file = 'openstack-blueprint.yaml'
        hello.inputs.update({
            'agent_user': attributes.centos_7_username,
            'image': attributes.centos_7_image_name,
            'manager_network_name': network_name,
            'network_name': network_id,
        })

        # Make sure the post_bootstrap network is first
        if network_name == NETWORK_2:
            hellos.insert(0, hello)
        else:
            hellos.append(hello)

    # Add one more hello world, that will run on the `default` network
    # implicitly
    hw = centos_hello_world(cfy, manager, attributes, ssh_key, logger, tmpdir,
                            tenant=DEFAULT_TENANT_NAME,
                            suffix='default_network')
    # Upload openstack plugin to default tenant
    manager.upload_plugin(attributes.default_openstack_plugin,
                          tenant_name=DEFAULT_TENANT_NAME)
    hellos.append(hw)

    yield hellos
    for hello in hellos:
        hello.cleanup()


@pytest.fixture(scope='function')
def multi_network_hello_worlds(cfy, managers, attributes, ssh_key, tmpdir,
                               logger):
    # unfortunately, pytest wants the fixtures to be generators syntactically
    # so we can't just do `return _make_network..()` when factoring out
    # common functionality, we need to do this silly thing.
    # In python 2.x, we don't have `yield from` either.
    for _x in _make_network_hello_worlds(cfy, managers, attributes, ssh_key,
                                         tmpdir, logger):
        yield _x


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


def test_agent_via_proxy(cfy,
                         proxy_hosts,
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
        cfy, manager, ssh_key, logger, 'agent_via_proxy', vm)
    example.upload_and_verify_install()
    example.uninstall()
