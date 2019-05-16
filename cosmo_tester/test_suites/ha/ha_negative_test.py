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

import time
import pytest
from cosmo_tester.framework.test_hosts import TestHosts
from . import skip_community
from . import ha_helper

# Skip all tests in this module if we're running community tests,
# using the pytestmark magic variable name
pytestmark = skip_community


@pytest.fixture(scope='function')
def hosts(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a HA cluster from an image in rackspace OpenStack."""
    logger.info('Creating HA cluster of 2 managers')
    hosts = TestHosts(
        cfy, ssh_key, module_tmpdir, attributes, logger,
        number_of_instances=2, request=request)

    # manager2 - Cloudify latest - don't install plugins
    hosts.instances[1].upload_plugins = False

    try:
        hosts.create()
        ha_helper.setup_cluster(hosts.instances, cfy, logger)
        yield hosts

    finally:
        hosts.destroy()


def test_remove_from_cluster_and_use_negative(cfy, hosts, logger):
    manager1 = hosts.instances[0]
    manager2 = hosts.instances[1]

    logger.info('Removing the standby manager %s from the HA cluster',
                manager2.ip_address)
    cfy.cluster.nodes.remove(manager2.ip_address)

    # removing nodes from a cluster can lead to short breaks of the cluster
    # endpoints in the REST API in case Consul was using the removed node
    # as a Consul leader. Let's wait for re-election to check that after
    # removing node, the cluster still correctly shows a leader
    ha_helper.wait_leader_election([manager1], logger)

    logger.info('Trying to use a manager previously removed'
                ' from HA cluster')
    for retry in range(10):
        with pytest.raises(Exception) as exinfo:
            # use a separate profile name, to force creating a new profile
            # (pre-existing profile would be connected to the whole cluster,
            # which at this point consists only of manager1)
            manager2.use(profile_name='new-profile')

        # need to give the replica some time for it to notice it has been
        # removed and change the error message. This should happen on the
        # order of one to several seconds. On the last retry, it is required
        # that the message has already changed by then.
        if retry < 9 and 'It is not the active manager in the cluster.' in \
                exinfo.value.message:
            time.sleep(2)
            continue
        assert 'This node was removed from the Cloudify Manager cluster' in \
            exinfo.value.message
        break
    # we've tested the CLI, but let's check rejoin using the rest-client
    # directly. No need to retry because we already waited.
    with pytest.raises(Exception) as exinfo:
        manager2.client.cluster.join(
            host_ip=manager2.private_ip_address,
            node_name=manager2.private_ip_address,
            join_addrs=[manager1.private_ip_address],
            credentials={})
    assert 'This node was removed from the Cloudify Manager cluster' in \
        exinfo.value.message
