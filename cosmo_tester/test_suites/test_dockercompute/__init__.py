########
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
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

import json as _json
import sys
import shutil

from path import path

from cosmo_tester.framework import dockercompute
from cosmo_tester.framework import util
from cosmo_tester.framework.testenv import bootstrap, teardown, TestCase


def setUp():
    bootstrap()


def tearDown():
    teardown()


class DockerComputeTestCase(TestCase):

    def setUp(self):
        super(DockerComputeTestCase, self).setUp()
        dockercompute.manager_setup()

    def tearDown(self):
        # I would rather have this clean added using addCleanup
        # problem is env.management_ip may be cleared by a test
        # using addCleanup and when we get to this point we no longer
        # have an ip. addCleanup funcs are called *after* tearDown
        # so we should be good (hopefully)
        with self.manager_env_fabric(warn_only=True) as api:
            api.run(
                'docker -H {0} rm -f $('
                'docker -H {0} ps -aq --filter '
                'ancestor=cloudify/centos-plain:7)'
                .format(self.docker_host))
        super(DockerComputeTestCase, self).tearDown()

    def request(self, url, method='GET', json=False, connect_timeout=10):
        command = "curl -X {0} --connect-timeout {1} '{2}'".format(
            method, connect_timeout, url)
        try:
            with self.manager_env_fabric() as api:
                result = api.run(command)
            if json:
                result = _json.loads(result)
            return result
        except:
            tpe, value, tb = sys.exc_info()
            raise RuntimeError, RuntimeError(str(value)), tb

    def ip(self, node_id, deployment_id=None):
        return self._instance(
            node_id,
            deployment_id=deployment_id).runtime_properties['ip']

    def key_path(self, node_id, deployment_id=None):
        return self._instance(
            node_id,
            deployment_id=deployment_id).runtime_properties[
            'cloudify_agent']['key']

    def kill_container(self, node_id, deployment_id=None):
        container_id = self._instance(
            node_id,
            deployment_id=deployment_id).runtime_properties['container_id']
        with self.manager_env_fabric() as api:
            api.run('docker -H {0} rm -f {1}'.format(
                self.docker_host, container_id))

    def _instance(self, node_id, deployment_id):
        deployment_id = deployment_id or self.test_id
        return self.client.node_instances.list(
            node_id=node_id, deployment_id=deployment_id)[0]

    @staticmethod
    def blueprint_resource_path(resource_path):
        return util.get_resource_path('dockercompute/blueprints/{0}'.format(
            resource_path))

    def add_plugin_yaml_to_blueprint(self, blueprint_yaml=None):
        blueprint_yaml = blueprint_yaml or self.blueprint_yaml
        blueprint_yaml = path(blueprint_yaml)
        target_plugin_yaml_name = 'dockercompute-plugin.yaml'
        with util.YamlPatcher(blueprint_yaml) as patcher:
            patcher.obj['imports'].append(target_plugin_yaml_name)
        shutil.copy(util.get_resource_path('dockercompute/plugin.yaml'),
                    blueprint_yaml.dirname() / target_plugin_yaml_name)

    @property
    def docker_host(self):
        return self.env.handler_configuration.get('docker_host', 'fd://')
