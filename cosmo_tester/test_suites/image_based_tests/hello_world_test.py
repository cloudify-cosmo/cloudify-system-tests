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

from cosmo_tester.framework.examples.hello_world import (  # noqa
    HelloWorldExample,
    hello_worlds
)
from cosmo_tester.framework.fixtures import image_based_manager
from cosmo_tester.framework.util import prepare_and_get_test_tenant

manager = image_based_manager


def test_hello_world(hello_world):
    hello_world.verify_all()


def test_hello_world_backwards(hello_world_backwards_compat):
    hello_world_backwards_compat.verify_all()


def test_hello_world_using_cfy_install_command(hello_worlds):  # noqa
    # Run the test twice: community and premium
    for hw in hello_worlds:
        hw.run_cfy_install_command()
        hw.run_cfy_uninstall_command()


@pytest.fixture(
    scope='function',
    params=[
        'centos_6',
        'centos_7',
        'rhel_6',
        'rhel_7',
        'ubuntu_14_04',
        'ubuntu_16_04',
        'windows_2012',
    ],
)
def hello_world(request, cfy, manager, attributes, ssh_key, tmpdir, logger):
    tenant = prepare_and_get_test_tenant(request.param, manager, cfy)
    hw = HelloWorldExample(
            cfy, manager, attributes, ssh_key, logger, tmpdir,
            tenant=tenant, suffix=request.param)
    if 'windows' in request.param:
        hw.blueprint_file = 'openstack-windows-blueprint.yaml'
        hw.inputs.update({
            'flavor': attributes['large_flavor_name'],
        })
    else:
        hw.blueprint_file = 'openstack-blueprint.yaml'
        hw.inputs.update({
            'agent_user': attributes['{os}_username'.format(os=request.param)],
        })
    if request.param == 'rhel_7':
        hw.inputs.update({
            'flavor': attributes['medium_flavor_name'],
        })

    hw.inputs.update({
        'image': attributes['{os}_image_name'.format(os=request.param)],
    })

    if request.param == 'centos_6':
        hw.disable_iptables = True
    yield hw
    hw.cleanup()
