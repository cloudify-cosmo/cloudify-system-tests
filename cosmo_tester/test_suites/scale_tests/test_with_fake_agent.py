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

import yaml

import pytest

from cosmo_tester.framework.test_hosts import TestHosts, IMAGES


BLUEPRINT = 'fake-agent-blueprint'
DEPLOYMENT = 'fake-agent-deployment'

AGENT_HOSTS = 4


def test_manager_agent_scaling(cfy, ssh_key, hosts):
    manager = hosts.instances[0]
    agent_hosts = hosts.instances[1:]
    host_scale = len(agent_hosts)

    with open(ssh_key.private_key_path) as f:
        key = f.read()
    manager.client.secrets.create('agent_host_key', key)
    manager.upload_plugin('host-pool_centos_core')

    pool = {'hosts': [
                    {
                        'name': 'host-pool-agent-host-{}'.format(i),
                        'os': 'linux',
                        'credentials': {
                            'username': 'centos',
			    'key': {'get_secret': 'agent_host_key'},
			    },
                        'endpoint': {
                            'ip': host.ip_address,
                            'port': 22,
                            'protocol': 'ssh',
                            }
                    }
                    for i, host in enumerate(agent_hosts)
                ],
            }

    blueprint_dir = os.path.join(
        os.path.dirname(__file__),
        '../../resources/blueprints/',
        'fake-agent-scale',
        )

    with open(os.path.join(blueprint_dir, 'pool.yaml'), 'w') as f:
        f.write(yaml.dump(pool))

    manager.client.blueprints.upload(
            os.path.join(blueprint_dir, 'blueprint.yaml'),
            'fake-agent-blueprint',
            )

    deployment = manager.client.deployments.create(
            BLUEPRINT,
            DEPLOYMENT,
            inputs={
                'host_user': 'centos',
                'host_scale': host_scale,
                'agent_scale': 15,
                },
            )

    cfy.executions.start.install(['-d', DEPLOYMENT])

    executions = manager.client.executions.list(
            deployment_id=deployment.id,
            workflow_id='install',
            )
    install = executions[0]

    assert install.status == 'terminated'

    with manager.ssh() as fabric:
        rabbit_connections = fabric.sudo('rabbitmqctl list_connections')

    default_tenant_connections = (
            x for x in rabbit_connections.splitlines()
            if 'default_tenant' in x
            )

    # There will be a few extras (mgmtworkers) so < double ensures only one
    # connection per remote agent
    assert len(list(default_tenant_connections)) < 30


@pytest.fixture
def hosts(cfy, ssh_key, module_tmpdir, attributes, logger):

    instances = [IMAGES[x]() for x in ['master'] + ['centos']*AGENT_HOSTS]

    hosts = TestHosts(
            cfy, ssh_key, module_tmpdir, attributes, logger,
            instances=instances)

    try:
        hosts.create()
        instances[0].use()
        yield hosts
    finally:
        hosts.destroy()
