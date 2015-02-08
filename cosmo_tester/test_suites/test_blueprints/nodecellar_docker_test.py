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

# Cloudify Imports
from cosmo_tester.test_suites.test_blueprints.nodecellar_test \
    import NodecellarAppTest


class DockerNodecellarTests(NodecellarAppTest):

    def test_docker_nodecellar(self):
        self._test_nodecellar_impl('docker-openstack-blueprint.yaml')

    @property
    def repo_url(self):
        return 'https://github.com/cloudify-cosmo/' \
               'cloudify-nodecellar-docker-example.git'

    @property
    def blueprint_directory(self):
        return 'blueprint'

    @property
    def expected_nodes_count(self):
        return 6

    @property
    def host_expected_runtime_properties(self):
        return ['ip', 'container_id', 'ports', 'network_settings', 'image_id']

    @property
    def entrypoint_node_name(self):
        return 'nodecellar_floatingip'

    @property
    def entrypoint_property_name(self):
        return 'floating_ip_address'
