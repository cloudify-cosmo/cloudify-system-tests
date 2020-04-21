########
# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
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
import time

from cloudify import constants
from cloudify.compute import create_multi_mimetype_userdata
from cloudify.mocks import MockCloudifyContext
from cloudify.state import current_ctx
from cloudify_agent.api import defaults
from cloudify_agent.installer import script
from cosmo_tester.framework import util
from cosmo_tester.framework.fixtures import image_based_manager
from cosmo_tester.framework.util import (
    set_client_tenant,
    prepare_and_get_test_tenant,
)

manager = image_based_manager


EXPECTED_FILE_CONTENT = 'CONTENT'


def test_windows_provided_userdata_agent(cfy,
                                         manager,
                                         attributes,
                                         tmpdir,
                                         logger):
    name = 'cloudify_agent'
    tenant = prepare_and_get_test_tenant(
        'userdataprov_windows_2012',
        manager,
        cfy,
    )
    user = 'Admin'
    install_userdata = _install_script(
        name=name,
        windows=True,
        user=user,
        manager=manager,
        attributes=attributes,
        tmpdir=tmpdir,
        logger=logger,
        tenant=tenant,
    )
    file_path = 'C:\\Users\\{0}\\test_file'.format(user)
    userdata = '#ps1_sysnative\n' \
               'Set-Content {1} "{0}"'.format(EXPECTED_FILE_CONTENT, file_path)
    userdata = create_multi_mimetype_userdata([userdata,
                                               install_userdata])
    inputs = {
        'image': attributes.windows_2012_image_name,
        'user': user,
        'flavor': attributes.medium_flavor_name,
        'os_family': 'windows',
        'userdata': userdata,
        'file_path': file_path,
        'install_method': 'provided',
        'name': name,
        'keypair_name': attributes.keypair_name,
        'private_key_path': manager.remote_private_key_path,
        'network_name': attributes.network_name
    }
    _test_userdata_agent(cfy, manager, inputs, tenant)


def _test_userdata_agent(cfy, manager, inputs, tenant):
    blueprint_id = deployment_id = 'userdata{0}'.format(time.time())
    blueprint_path = util.get_resource_path(
        'agent/userdata-agent-blueprint/userdata-agent-blueprint.yaml')

    with set_client_tenant(manager, tenant):
        manager.client.blueprints.upload(blueprint_path, blueprint_id)
        manager.client.deployments.create(
            deployment_id,
            blueprint_id,
            inputs=inputs,
            skip_plugins_validation=True)

    cfy.executions.start.install(['-d', deployment_id,
                                  '--tenant-name', tenant])

    try:
        with set_client_tenant(manager, tenant):
            assert {
                'MY_ENV_VAR': 'MY_ENV_VAR_VALUE',
                'file_content': EXPECTED_FILE_CONTENT
            } == manager.client.deployments.outputs.get(deployment_id).outputs
    finally:
        cfy.executions.start.uninstall(['-d', deployment_id,
                                        '--tenant-name', tenant])


def _install_script(name, windows, user, manager, attributes, tmpdir, logger,
                    tenant):
    # Download cert from manager in order to include its content
    # in the init_script.
    local_cert_path = str(tmpdir / 'cloudify_internal_cert.pem')
    logger.info('Downloading internal cert from manager: %s -> %s',
                attributes.LOCAL_REST_CERT_FILE,
                local_cert_path)
    manager.get_remote_file(attributes.LOCAL_REST_CERT_FILE, local_cert_path)

    env_vars = {
        constants.REST_HOST_KEY: manager.private_ip_address,
        constants.REST_PORT_KEY: str(defaults.INTERNAL_REST_PORT),
        constants.BROKER_SSL_CERT_PATH: local_cert_path,
        constants.LOCAL_REST_CERT_FILE_KEY: local_cert_path,
        constants.MANAGER_FILE_SERVER_URL_KEY: (
            'https://{0}:{1}/resources'.format(manager.private_ip_address,
                                               defaults.INTERNAL_REST_PORT)
        ),
        constants.MANAGER_FILE_SERVER_ROOT_KEY: str(tmpdir),
        constants.MANAGER_NAME: (
            manager.client.manager.get_managers()[0].hostname
        ),
    }
    (tmpdir / 'cloudify_agent').mkdir()

    ctx = MockCloudifyContext(
        node_id='node',
        tenant=manager.client.tenants.get(tenant),
        rest_token=manager.client.tokens.get().value,
        managers=manager.client.manager.get_managers(),
        brokers=manager.client.manager.get_brokers(),
        properties={'agent_config': {
            'user': user,
            'windows': windows,
            'install_method': 'init_script',
            'name': name
        }})
    try:
        current_ctx.set(ctx)
        os.environ.update(env_vars)
        script_builder = script._get_script_builder()
        install_script = script_builder.install_script()
    finally:
        for var_name in list(env_vars):
            os.environ.pop(var_name, None)

        current_ctx.clear()

    # Replace the `main` call with an install call - as we only want to
    # install the agent, but not configure/start it
    install_method = 'InstallAgent' if windows else 'install_agent'
    install_script = '\n'.join(install_script.split('\n')[:-1])
    return '{0}\n{1}'.format(install_script, install_method)
