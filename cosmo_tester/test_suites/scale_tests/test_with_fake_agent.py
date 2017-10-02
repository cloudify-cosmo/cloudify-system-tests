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

import os
import shutil

import pytest

from cosmo_tester.framework.test_hosts import TestHosts, IMAGES


BLUEPRINT = 'fake-agent-blueprint'
DEPLOYMENT = 'fake-agent-deployment'


def test_manager_agent_scaling(cfy, hosts):
    manager, agent_host = hosts.instances

    with open(agent_host.ssh_key) as f:
        key = f.read()
    manager.client.secrets.create('agent_host_key', key)

    blueprint_dir = os.path.join(
        os.path.dirname(__file__),
        '../../resources/blueprints/',
        'fake-agent-scale',
        )

    manager.client.blueprints.upload(
            os.path.join(blueprint_dir, 'blueprint.yaml'),
            'fake-agent-blueprint',
            )

    manager.client.deployments.create(
            BLUEPRINT,
            DEPLOYMENT,
            inputs={
                'host_ip': agent_host.private_ip_address,
                'host_user': 'centos',
                'key_file': agent_host.ssh_key,
                },
            )

    cfy.executions.start.install(['-d', DEPLOYMENT])


@pytest.fixture
def hosts(cfy, ssh_key, module_tmpdir, attributes, logger):

    instances = [IMAGES[x]() for x in ('master', 'centos')]

    hosts = TestHosts(
            cfy, ssh_key, module_tmpdir, attributes, logger,
            instances=instances)

    try:
        hosts.create()
        instances[0].use()
        yield hosts
    finally:
        hosts.destroy()
