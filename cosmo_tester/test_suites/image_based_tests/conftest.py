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

#from cosmo_tester.framework.cloudify_manager import CloudifyCluster


# @pytest.fixture(scope='module')
# def image_based_manager(
#         request, cfy, ssh_key, module_tmpdir, attributes, logger):
#     """Creates a cloudify manager from an image in rackspace OpenStack."""
#     cluster = CloudifyCluster.create_image_based(
#             cfy, ssh_key, module_tmpdir, attributes, logger)
#
#     yield cluster.managers[0]
#
#     cluster.destroy()
