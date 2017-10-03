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

import yaml
import json
import pytest
from os.path import join
from copy import deepcopy

from cosmo_tester.framework.test_hosts import BootstrapBasedCloudifyManagers
from cosmo_tester.framework.examples.hello_world import HelloWorldExample
from cosmo_tester.framework.util import prepare_and_get_test_tenant

from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    download_snapshot,
    upload_snapshot,
    restore_snapshot,
    upgrade_agents,
    delete_manager
)

NETWORK_0 = 'network_0'


@pytest.fixture(scope='module')
def managers(cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps 2 cloudify managers on a VM in rackspace OpenStack."""

    hosts = BootstrapBasedCloudifyManagers(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=2,
        tf_template='openstack-multi-network-test.tf.template',
        template_inputs={
            'num_of_networks': 3,
            'num_of_managers': 2,
            'image_name': attributes.centos_7_image_name
        })
    hosts.preconfigure_callback = _preconfigure_callback

    try:
        hosts.create()
        yield hosts.instances
    finally:
        hosts.destroy()


def _preconfigure_callback(_managers):
    # Calling the param `_managers` to avoid confusion with fixture

    # The preconfigure callback populates the networks config prior to the BS
    for mgr in _managers:
        # Remove one of the networks - it will be added post-bootstrap
        all_networks = deepcopy(mgr.networks)
        all_networks.pop(NETWORK_0)

        mgr.bs_inputs = {'manager_networks': all_networks}

        # Configure NICs in order for networking to work properly
        mgr.enable_nics()


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
        hello.upload_blueprint()
        hello.create_deployment()
        hello.install()
        hello.verify_installation()

    create_snapshot(old_manager, snapshot_id, attributes, logger)
    download_snapshot(old_manager, local_snapshot_path, snapshot_id, logger)
    upload_snapshot(new_manager, local_snapshot_path, snapshot_id, logger)
    restore_snapshot(new_manager, snapshot_id, cfy, logger)

    upgrade_agents(cfy, new_manager, logger)
    delete_manager(old_manager, logger)

    new_manager.use()
    for hello in multi_network_hello_worlds:
        hello.manager = new_manager
        hello.uninstall()
        hello.delete_deployment()

    _add_network_0(new_manager, tmpdir, logger)
    post_bootstrap_hello.verify_all()


def _add_network_0(manager, tmpdir, logger):
    logger.info('Adding network `{0}` to the new manager'.format(NETWORK_0))

    local_cert_metadata = tmpdir / 'certificate_metadata'
    remote_cert_metadata = '/etc/cloudify/ssl/certificate_metadata'
    private_ip = manager.networks['default']

    # This should add back NETWORK_0 we removed earlier
    cert_metadata = {
        'networks': manager.networks,
        'internal_rest_host': private_ip
    }
    with open(local_cert_metadata, 'w') as f:
        json.dump(cert_metadata, f)
    with manager.ssh() as fabric_ssh:
        logger.info('Putting a new `certificate_metadata` file')
        fabric_ssh.put(local_cert_metadata, remote_cert_metadata)

        ip_setter_path = '/opt/cloudify/manager-ip-setter/'
        restservice_python = '/opt/manager/env/bin/python'
        mgmtworker_python = '/opt/mgmtworker/env/bin/python'
        update_ctx_script = join(ip_setter_path, 'update-provider-context.py')
        certs_script = join(ip_setter_path, 'create-internal-ssl-certs.py')

        logger.info('Updating the provider context...')
        fabric_ssh.run('{0} {1} {2}'.format(
            restservice_python, update_ctx_script, private_ip
        ))

        logger.info('Recreating internal certs')
        fabric_ssh.run('{0} {1} {2}'.format(
            mgmtworker_python, certs_script, private_ip
        ))


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


@pytest.fixture(scope='function')
def multi_network_hello_worlds(cfy, managers, attributes, ssh_key, tmpdir,
                               logger):
    # The first manager is the initial one
    manager = managers[0]
    manager.use()
    hellos = []

    # Add a MultiNetworkHelloWorld per management network
    for network_name, network_id in attributes.network_names.iteritems():
        tenant = prepare_and_get_test_tenant(
            '{0}_tenant'.format(network_name), manager, cfy
        )
        hello = MultiNetworkHelloWorld(
            cfy, manager, attributes, ssh_key, logger, tmpdir,
            tenant=tenant, suffix=tenant)
        hello.blueprint_file = 'openstack-blueprint.yaml'
        hello.inputs.update({
            'agent_user': attributes.centos_7_username,
            'image': attributes.centos_7_image_name,
            'manager_network_name': network_name,
            'network_name': network_id
        })

        # Make sure the post_bootstrap network is first
        if network_name == NETWORK_0:
            hellos.insert(0, hellos)
        else:
            hellos.append(hello)

    # Add one more hello world, that will run on the `default` network
    # implicitly
    hw = HelloWorldExample(cfy, manager, attributes, ssh_key, logger, tmpdir)
    hw.blueprint_file = 'openstack-blueprint.yaml'
    hw.inputs.update({
        'agent_user': attributes.centos_7_username,
        'image': attributes.centos_7_image_name
    })
    hellos.append(hw)

    yield hellos
    for hello in hellos:
        hello.cleanup()
