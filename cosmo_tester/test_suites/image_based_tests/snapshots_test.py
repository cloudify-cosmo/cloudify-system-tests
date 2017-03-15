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

import uuid

import pytest
import retrying

from cosmo_tester.framework import examples
from cosmo_tester.framework.cluster import CloudifyCluster


@pytest.fixture(scope='module')
def cluster(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    cluster = CloudifyCluster.create_image_based(
            cfy,
            ssh_key,
            module_tmpdir,
            attributes,
            logger,
            number_of_managers=2)

    yield cluster

    cluster.destroy()


@pytest.fixture(scope='function')
def hello_world(cfy, cluster, attributes, ssh_key, tmpdir, logger):
    hw = examples.HelloWorldExample(
            cfy, cluster.managers[0], attributes, ssh_key, logger, tmpdir)
    hw.blueprint_file = 'openstack-blueprint.yaml'
    hw.inputs.update({
        'agent_user': attributes.centos7_username,
        'image': attributes.centos7_image_name,
    })

    yield hw
    if hw.cleanup_required:
        logger.info('Hello world cleanup required..')
        cluster.managers[0].use()
        hw.cleanup()


@retrying.retry(stop_max_attempt_number=10, wait_fixed=5000)
def _assert_snapshot_created(snapshot_id, client):
    snapshot = client.snapshots.get(snapshot_id)
    assert snapshot.status == 'created', 'Snapshot not in created status'
    if snapshot.status != 'created':
        raise AssertionError('Snapshot expected to be ')


def test_create_snapshot(cfy, cluster, hello_world, attributes, ssh_key, logger, tmpdir):
    """
    This test serves as an example for writing Cloudify cluster tests.
    This test is currently disabled as it is not 100% completed.
    """
    cluster.managers[0].use()
    hello_world.upload_blueprint()
    hello_world.create_deployment()
    hello_world.install()

    snapshot_id = str(uuid.uuid4())

    cluster.managers[0].use()
    cluster.managers[0].client.snapshots.create(snapshot_id, True, True)

    _assert_snapshot_created(snapshot_id, cluster.managers[0].client)
    cfy.snapshots.list()

    snapshot_archive_path = str(tmpdir / 'snapshot.zip')
    cluster.managers[0].client.snapshots.download(snapshot_id,
                                                  snapshot_archive_path)

    cluster.managers[1].client.snapshots.upload(snapshot_archive_path,
                                                snapshot_id)
    cluster.managers[1].client.snapshots.restore(snapshot_id)

    cluster.managers[1].use()
    cfy.snapshots.list()

    cfy.agents.install()

    hello_world.manager = cluster.managers[1]
    hello_world.uninstall()
    hello_world.delete_deployment()

