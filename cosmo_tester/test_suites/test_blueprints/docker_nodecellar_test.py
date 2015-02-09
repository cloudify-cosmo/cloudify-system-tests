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

import requests

# Cloudify Imports
from cosmo_tester.test_suites.test_blueprints.nodecellar_test \
    import NodecellarAppTest


class DockerNodecellarTests(NodecellarAppTest):

    def test_docker_nodecellar(self):
        self._test_nodecellar_impl('blueprint/docker-openstack-blueprint.yaml')

    def assert_nodecellar_working(self, public_ip):
        nodejs_server_page_response = requests.get('http://{0}:8080/#'
                                                   .format(self.public_ip))
        self.assertEqual(200, nodejs_server_page_response.status_code,
                         'Failed to get home page of nodecellar app')
        page_title = 'Node Cellar'
        self.assertTrue(page_title in nodejs_server_page_response.text,
                        'Expected to find {0} in web server response: {1}'
                        .format(page_title, nodejs_server_page_response))

        wines_page_response = requests.get('http://{0}:8080/#wines'.format(
            self.public_ip))
        self.assertEqual(200, wines_page_response.status_code,
                         'Failed to get the wines page on nodecellar app ('
                         'probably means a problem with the connection to '
                         'MongoDB)')

        wines_add_page_response = requests.get(
            'http://{0}:8080/#wines/add'.format(self.public_ip))
        self.assertEqual(200, wines_add_page_response.status_code,
                         'Failed to get the wines page on nodecellar app ('
                         'probably means a problem with the connection to '
                         'MongoDB)')

    @property
    def repo_url(self):
        return 'https://github.com/cloudify-cosmo/' \
               'cloudify-nodecellar-docker-example.git'

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

    def get_inputs(self):
        return {}

    def assert_monitoring_data_exists(self):
        pass
