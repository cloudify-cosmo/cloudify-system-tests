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

from cosmo_tester.framework.cluster import CloudifyCluster


@pytest.fixture(scope='module', params=[3])
def manager(request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps a cloudify manager on a VM in rackspace OpenStack."""
    cluster = CloudifyCluster.create_bootstrap_based(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        tf_template='openstack-multi-network-test.tf.template',
        template_inputs={
            'num_of_networks': request.param,
            'image_name': attributes['centos_7_image_name']
        },
        preconfigure_callback=_preconfigure_callback
    )

    yield cluster.managers[0]

    cluster.destroy()


def _preconfigure_callback(managers):
    # The preconfigure callback populates the networks config prior to the BS
    mgr = managers[0]
    mgr.bs_inputs = {'manager_networks': mgr._attributes.networks}


def test_multiple_networks(manager, cfy, logger):
    logger.info('Testing manager with multiple networks')
    manager.use()
    manager.stop_for_user_input()
