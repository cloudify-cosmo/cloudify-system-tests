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

import json
import pytest

from cosmo_tester.framework.examples import get_example_deployment


def test_simple_deployment(example_deployment):
    example_deployment.upload_and_verify_install()


def test_simple_deployment_using_cfy_install_command(example_deployment, cfy):
    example_deployment.set_agent_key_secret()
    example_deployment.manager.use()
    cfy.install(
        '--tenant-name', example_deployment.tenant,
        '--blueprint-id', example_deployment.blueprint_id,
        '--deployment-id', example_deployment.deployment_id,
        '--inputs', json.dumps(example_deployment.inputs),
        example_deployment.blueprint_file,
    )


@pytest.fixture(scope='function')
def example_deployment(cfy, image_based_manager, attributes, ssh_key, tmpdir,
                       logger, request):
    example = get_example_deployment(
        cfy, image_based_manager, ssh_key, logger, request.node.name)

    yield example
    example.uninstall()
