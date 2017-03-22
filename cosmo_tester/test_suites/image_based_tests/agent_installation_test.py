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
import uuid
import time

import pytest
import testtools

from cloudify import constants
from cloudify_agent.api import defaults
from cloudify_agent.installer import script
from cloudify.state import current_ctx
from cloudify.mocks import MockCloudifyContext
from cloudify.compute import create_multi_mimetype_userdata
from cosmo_tester.framework import util


from cosmo_tester.framework.fixtures import image_based_manager as manager  # noqa



def test_3_2_agent(cfy, manager, attributes):
    blueprint_path = util.get_resource_path(
            'agent/3-2-agent-blueprint/3-2-agent-mispelled-blprint.yaml')

    blueprint_id = deployment_id = str(uuid.uuid4())

    manager.client.blueprints.upload(blueprint_path, blueprint_id)
    manager.client.deployments.create(
            deployment_id, blueprint_id, inputs={
                'ip_address': manager.ip_address,
                'user': attributes.centos7_username,
                'private_key_path': manager.remote_private_key_path
            })
    try:
        cfy.executions.start.install(['-d', deployment_id])
    finally:
        cfy.executions.start.uninstall(['-d', deployment_id])


def test_ssh_agent(cfy, manager, attributes):
    blueprint_path = util.get_resource_path(
            'agent/ssh-agent-blueprint/ssh-agent-blueprint.yaml')

    blueprint_id = deployment_id = str(uuid.uuid4())

    manager.client.blueprints.upload(blueprint_path, blueprint_id)
    manager.client.deployments.create(
            deployment_id, blueprint_id, inputs={
                'ip_address': manager.ip_address,
                'user': attributes.centos7_username,
                'private_key_path': manager.remote_private_key_path
            })
    try:
        cfy.executions.start.install(['-d', deployment_id])
    finally:
        cfy.executions.start.uninstall(['-d', deployment_id])


def _test_agent_alive_after_reboot(cfy, manager, blueprint_name, inputs):

    blueprint_path = util.get_resource_path(blueprint_name)
    value = str(uuid.uuid4())
    inputs['value'] = value
    blueprint_id = deployment_id = str(uuid.uuid4())

    manager.client.blueprints.upload(blueprint_path, blueprint_id)
    manager.client.deployments.create(
            deployment_id, blueprint_id, inputs=inputs)

    cfy.executions.start.install(['-d', deployment_id])
    cfy.executions.start.execute_operation(
            deployment_id=deployment_id,
            parameters={
                'operation': 'cloudify.interfaces.reboot_test.reboot',
                'node_ids': ['host']
            })
    cfy.executions.start.uninstall(['-d', deployment_id])
    app = manager.client.node_instances.list(node_id='application',
                                             deployment_id=deployment_id)[0]
    assert value == app.runtime_properties['value']


def test_ubuntu_agent_alive_after_reboot(cfy, manager, attributes):

    _test_agent_alive_after_reboot(
            cfy,
            manager,
            blueprint_name='agent/reboot-vm-blueprint/'
                           'reboot-unix-vm-blueprint.yaml',
            inputs={
                'image': attributes.ubuntu_14_04_image_name,
                'flavor': attributes.medium_flavor_name,
                'user': attributes.ubuntu_username,
                'network_name': attributes.network_name,
                'private_key_path': manager.remote_private_key_path,
                'keypair_name': attributes.keypair_name
            })


def test_centos_agent_alive_after_reboot(cfy, manager, attributes):

    _test_agent_alive_after_reboot(
            cfy,
            manager,
            blueprint_name='agent/reboot-vm-blueprint/'
                           'reboot-unix-vm-blueprint.yaml',
            inputs={
                'image': attributes.centos7_image_name,
                'flavor': attributes.small_flavor_name,
                'user': attributes.centos7_username,
                'network_name': attributes.network_name,
                'private_key_path': manager.remote_private_key_path,
                'keypair_name': attributes.keypair_name
            })


def test_winrm_agent_alive_after_reboot(cfy, manager, attributes, logger):

    logger.info('### SLEEPING ###')
    import time
    time.sleep(60*2)

    _test_agent_alive_after_reboot(
            cfy,
            manager,
            blueprint_name='agent/reboot-vm-blueprint/'
                           'reboot-winrm-vm-blueprint.yaml',
            inputs={
                'image': attributes.windows_server_2012_image_name,
                'flavor': attributes.medium_flavor_name,
                'user': attributes.windows_server_2012_username,
                'network_name': attributes.network_name,
                'private_key_path': manager.remote_private_key_path,
                'keypair_name': attributes.keypair_name
            })


class AgentInstallerTest(testtools.TestCase):

    expected_file_content = 'CONTENT'

    def test_winrm_agent(self):

        self.blueprint_yaml = util.get_resource_path(
                'agent/winrm-agent-blueprint/winrm-agent-blueprint.yaml')
        self.upload_deploy_and_execute_install(
                inputs={
                    'image': self.env.windows_image_name,
                    'flavor': self.env.medium_flavor_id
                }
        )
        self.execute_uninstall()

    # Two different tests for ubuntu/centos
    # because of different disable requiretty logic
    def test_centos_core_userdata_agent(self):
        self._test_linux_userdata_agent(image=self.env.centos_7_image_name,
                                        flavor=self.env.small_flavor_id,
                                        user=self.env.centos_7_image_user,
                                        install_method='init_script')

    def test_ubuntu_trusty_userdata_agent(self):
        self._test_linux_userdata_agent(image=self.env.ubuntu_trusty_image_id,
                                        flavor=self.env.small_flavor_id,
                                        user='ubuntu',
                                        install_method='init_script')

    def test_ubuntu_trusty_provided_userdata_agent(self):
        name = 'cloudify_agent'
        user = 'ubuntu'
        install_userdata = install_script(name=name,
                                          windows=False,
                                          user=user,
                                          manager_host=self._manager_host())
        self._test_linux_userdata_agent(image=self.env.ubuntu_trusty_image_id,
                                        flavor=self.env.small_flavor_id,
                                        user=user,
                                        install_method='provided',
                                        name=name,
                                        install_userdata=install_userdata)

    def _test_linux_userdata_agent(self, image, flavor, user, install_method,
                                   install_userdata=None, name=None):
        file_path = '/tmp/test_file'
        userdata = '#! /bin/bash\necho {0} > {1}\nchmod 777 {1}'.format(
                self.expected_file_content, file_path)
        if install_userdata:
            userdata = create_multi_mimetype_userdata([userdata,
                                                       install_userdata])
        self._test_userdata_agent(image=image,
                                  flavor=flavor,
                                  user=user,
                                  os_family='linux',
                                  userdata=userdata,
                                  file_path=file_path,
                                  install_method=install_method,
                                  name=name)

    def test_windows_userdata_agent(self,
                                    install_method='init_script',
                                    name=None,
                                    install_userdata=None):
        user = 'Administrator'
        file_path = 'C:\\Users\\{0}\\test_file'.format(user)
        userdata = '#ps1_sysnative \nSet-Content {1} "{0}"'.format(
                self.expected_file_content, file_path)
        if install_userdata:
            userdata = create_multi_mimetype_userdata([userdata,
                                                       install_userdata])
        self._test_userdata_agent(image=self.env.windows_image_name,
                                  flavor=self.env.medium_flavor_id,
                                  user=user,
                                  os_family='windows',
                                  userdata=userdata,
                                  file_path=file_path,
                                  install_method=install_method,
                                  name=name)

    def test_windows_provided_userdata_agent(self):
        name = 'cloudify_agent'
        install_userdata = install_script(name=name,
                                          windows=True,
                                          user='Administrator',
                                          manager_host=self._manager_host())
        self.test_windows_userdata_agent(install_method='provided',
                                         name=name,
                                         install_userdata=install_userdata)

    def _test_userdata_agent(self, image, flavor, user, os_family,
                             userdata, file_path, install_method,
                             name=None):
        deployment_id = 'userdata{0}'.format(time.time())
        self.blueprint_yaml = util.get_resource_path(
                'agent/userdata-agent-blueprint/userdata-agent-blueprint.yaml')
        self.upload_deploy_and_execute_install(
                deployment_id=deployment_id,
                inputs={
                    'image': image,
                    'flavor': flavor,
                    'agent_user': user,
                    'os_family': os_family,
                    'userdata': userdata,
                    'file_path': file_path,
                    'install_method': install_method,
                    'name': name
                }
        )
        self.assert_outputs({'MY_ENV_VAR': 'MY_ENV_VAR_VALUE',
                             'file_content': self.expected_file_content},
                            deployment_id=deployment_id)
        self.execute_uninstall(deployment_id=deployment_id)

    def _manager_host(self):
        nova_client, _, _ = self.env.handler.openstack_clients()
        for server in nova_client.servers.list():
            if server.name == self.env.management_server_name:
                for network, network_ips in server.networks.items():
                    if network == self.env.management_network_name:
                        return network_ips[0]
        self.fail('Failed finding manager rest host')


def install_script(name, windows, user, manager_host):

    env_vars = {}
    env_vars[constants.REST_PORT_KEY] = str(defaults.INTERNAL_REST_PORT)
    env_vars[constants.MANAGER_FILE_SERVER_URL_KEY] = \
        'https://{0}:{1}/resources'.format(
                manager_host,
                defaults.INTERNAL_REST_PORT
        )

    ctx = MockCloudifyContext(
            node_id='node',
            properties={'agent_config': {
                'user': user,
                'windows': windows,
                'install_method': 'provided',
                'rest_host': manager_host,
                'broker_ip': manager_host,
                'name': name
            }})
    try:
        current_ctx.set(ctx)
        os.environ.update(env_vars)

        init_script = script.init_script(cloudify_agent={})
    finally:
        for var_name in env_vars.iterkeys():
            os.environ.pop(var_name)

        current_ctx.clear()
    result = '\n'.join(init_script.split('\n')[:-1])
    if windows:
        return '{0}\n' \
               'DownloadAndExtractAgentPackage\n' \
               'ExportDaemonEnv\n' \
               'ConfigureAgent'.format(result)
    else:
        return '{0}\n' \
               'install_agent'.format(result)
