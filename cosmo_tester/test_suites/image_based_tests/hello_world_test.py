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

import pytest

from cosmo_tester.framework.examples.hello_world import HelloWorldExample
from cosmo_tester.framework.fixtures import image_based_manager_with_tenants
from cosmo_tester.framework.util import get_test_tenants, create_test_tenants
from cosmo_tester.framework.cluster import CloudifyCluster, MANAGERS
from cosmo_tester.framework.hello_world import upload_and_install_helloworld, remove_and_check_deployments


#@pytest.fixture(scope='function')
#def hello_world(cfy, manager, attributes, ssh_key, tmpdir, logger):
#    hw = HelloWorldExample(
#            cfy, manager, attributes, ssh_key, logger, tmpdir)
#    hw.blueprint_file = 'openstack-blueprint.yaml'
#    yield hw
#    hw.cleanup()
OS_LIST = [
    'centos_6',  # TODO: MAKE UNBROKEN
    #'centos_7',
    #'rhel_6',
    #'rhel_7',
    #'ubuntu_14_04',
    #'ubuntu_16_04',
]


def test_hello_world(cfy, test_hosts, attributes, logger, tmpdir):
    agent_user = attributes['{os}_username'.format(os=test_hosts['targets_os'])]
    for tenant in get_test_tenants():
        upload_and_install_helloworld(attributes, logger, test_hosts['manager'],
                                      test_hosts['targets'][tenant],
                                      tmpdir, tenant=tenant, prefix=tenant,
                                      agent_user=agent_user)

    remove_and_check_deployments(test_hosts['targets'].values(), test_hosts['manager'], logger,
                                 get_test_tenants(), with_prefixes=True)

def _test_hello_world_on_windows_2012_server(hello_world, attributes):
    hello_world.blueprint_file = 'openstack-windows-blueprint.yaml'
    hello_world.inputs.update({
        'image': attributes.windows_server_2012_image_name,
        'flavor': attributes.medium_flavor_name
    })
    hello_world.verify_all()


@pytest.fixture(scope='module',
                params=OS_LIST)
def test_hosts(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """
        Creates a cloudify manager with tenants and targets for singlehost
        deployments for those tenants.
    """
    tenants = get_test_tenants()

    manager = [
        MANAGERS['master'](upload_plugins=False),
    ]
    target_vms = [
        MANAGERS['notamanager'][request.param](upload_plugins=False)
        for i in range(len(tenants))
    ]
    managers = manager + target_vms

    cluster = CloudifyCluster.create_image_based(
            cfy,
            ssh_key,
            module_tmpdir,
            attributes,
            logger,
            managers=managers,
            )
    cluster.managers[0].use()
    create_test_tenants(cfy)

    hosts = {
        'manager': cluster.managers[0],
        'targets': {
            tenants[pos]: cluster.managers[pos + 1]
            for pos in range(len(tenants))
        },
        'targets_os': request.param,
    }

    yield hosts

    cluster.destroy()

