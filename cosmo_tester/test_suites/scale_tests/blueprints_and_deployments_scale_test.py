########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
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
from datetime import datetime
from resource_creator import ResourceCreator
from cosmo_tester.framework.examples.hello_world import HelloWorldExample
from cosmo_tester.framework.fixtures import image_based_manager


@pytest.fixture(scope='module')
def module_hello_world(
        cfy, manager, attributes, ssh_key, module_tmpdir, logger):
    hello_world = HelloWorldExample(
        cfy, manager, attributes, ssh_key, logger, module_tmpdir)
    hello_world.blueprint_file = 'openstack-blueprint.yaml'
    hello_world.inputs.update({
        'agent_user': attributes.centos7_username,
        'image': attributes.centos7_image_name,
    })

    yield hello_world
    hello_world.cleanup()


manager = image_based_manager
blueprint_example = module_hello_world


@pytest.fixture(scope='module')
def resource_creator(manager, blueprint_example, logger):
    creator = ResourceCreator(manager, blueprint_example, logger)
    yield creator


@pytest.fixture(scope='module')
def resource_creator_hello_world(manager, blueprint_example, logger):
    import pydevd
    pydevd.settrace('192.168.8.80', port=53100, stdoutToServer=True,
                    stderrToServer=True, suspend=False)
    creator = ResourceCreator(manager, blueprint_example, logger)
    yield creator


@pytest.fixture(scope='module')
def resource_creator_nodeceller(manager, blueprint_example, logger):
    creator = ResourceCreator(manager, blueprint_example, logger)
    yield creator


@pytest.mark.parametrize("resource_creator", [
    'resource_creator_hello_world',
    'resource_creator_nodeceller'
])
def test_basic_api_with_many_deployments(resource_creator, request):
    """
    Test basic api with many deployments
    """
    # Getting a fixture by name
    # https://github.com/pytest-dev/pytest/issues/349#issuecomment-112203541
    resource_creator = request.getfixturevalue(resource_creator)
    resource_count = 10
    processes_count = 2
    resource_creator.upload_blueprints(resource_count, processes_count)
    resource_creator.create_deployments(resource_count, processes_count)
    _check_response_time(resource_creator.client, resource_creator.logger)
    resource_creator.delete_deployments(resource_count, processes_count)


def test_many_deployments_creation(resource_creator):
    """
    Test many deployments creation simultaneously
    """
    resource_count = 100
    processes_count = 10
    resource_creator.upload_blueprints(1, 1)
    # resource_creator.upload_blueprints(resource_count, processes_count)
    resource_creator.create_deployments(resource_count, processes_count)
    resource_creator.delete_deployments(resource_count, processes_count)


def test_many_deployments_snapshot(resource_creator):
    """
    Test snapshot creation when we have many deployments
    """
    resource_count = 500
    processes_count = 2
    resource_creator.upload_blueprints(resource_count, processes_count)
    resource_creator.create_deployments(resource_count, processes_count)
    resource_creator.create_snapshot()
    resource_creator.delete_deployments(resource_count, processes_count)


def _check_response_time(client, logger):
    """
    Currently just measuring the response time and later we will set the
    threshold for its assertion
    """
    responses_time = []

    for i in xrange(3):
        start = datetime.now()
        client.blueprints.list()
        responses_time.append((datetime.now() - start).total_seconds() * 1000)

    logger.info('Blueprint list response time is {} milliseconds'.
                format(sum(responses_time) / len(responses_time)))
