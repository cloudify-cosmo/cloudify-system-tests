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
import os
import uuid

import pytest
import retrying

from cosmo_tester.framework.cluster import (
    CloudifyCluster,
    MANAGERS,
)


HELLO_WORLD_URL = 'https://github.com/cloudify-cosmo/cloudify-hello-world-example/archive/4.0.zip'  # noqa


@pytest.fixture(
        scope='module',
        params=['4.0', '3.4'])
def cluster(request, cfy, ssh_key, module_tmpdir, attributes, logger):
    managers = (
        MANAGERS[request.param](),
        MANAGERS['master'](upload_plugins=False),
    )

    cluster = CloudifyCluster.create_image_based(
            cfy,
            ssh_key,
            module_tmpdir,
            attributes,
            logger,
            managers=managers,
            )

    yield cluster

    cluster.destroy()


@pytest.fixture(autouse=True)
def _hello_world_example(cluster, attributes, logger, tmpdir):
    _deploy_helloworld(attributes, logger, cluster.managers[0], tmpdir)

    yield

    if not cluster.managers[0].deleted:
        try:
            logger.info('Performing test cleanup..')
            with cluster.managers[0].ssh() as fabric:
                fabric.run('cfy executions start uninstall -d {0} '
                           '-p ignore_failure=true'.format(deployment_id))
        except Exception as e:
            logger.error('Error on test cleanup: %s', e)


blueprint_id = deployment_id = str(uuid.uuid4())


def test_restore_snapshot_and_agents_upgrade(
        cfy, cluster, attributes, logger, tmpdir):
    manager1 = cluster.managers[0]
    manager2 = cluster.managers[1]

    snapshot_id = str(uuid.uuid4())

    logger.info('Creating snapshot on manager1..')
    manager1.client.snapshots.create(snapshot_id, False, False, False)
    manager1.assert_snapshot_created(snapshot_id, attributes)

    local_snapshot_path = str(tmpdir / 'snapshot.zip')

    logger.info('Downloading snapshot from old manager..')
    manager1.client.snapshots.list()
    manager1.client.snapshots.download(snapshot_id, local_snapshot_path)

    manager2.use()
    logger.info('Uploading snapshot to latest manager..')
    snapshot = manager2.client.snapshots.upload(local_snapshot_path,
                                                snapshot_id)
    logger.info('Uploaded snapshot:%s%s',
                os.linesep,
                json.dumps(snapshot, indent=2))

    cfy.snapshots.list()

    logger.info('Restoring snapshot on latest manager..')
    restore_execution = manager2.client.snapshots.restore(snapshot_id)
    logger.info('Snapshot restore execution:%s%s',
                os.linesep,
                json.dumps(restore_execution, indent=2))

    cfy.executions.list(['--include-system-workflows'])

    _assert_restore_workflow_terminated(restore_execution.id,
                                        manager2.client,
                                        logger)

    cfy.executions.list(['--include-system-workflows'])

    cfy.deployments.list()
    deployments = manager2.client.deployments.list()
    assert 1 == len(deployments)

    logger.info('Upgrading agents..')
    cfy.agents.install()

    logger.info('Deleting 4.0 manager..')
    manager1.delete()

    logger.info('Uninstalling deployment from latest manager..')
    cfy.executions.start.uninstall(['-d', deployment_id])
    cfy.deployments.delete(deployment_id)


def _deploy_helloworld(attributes, logger, manager1, tmpdir):
    logger.info('Uploading helloworld blueprint to 4.0 manager..')
    inputs = {
        'floating_network_id': attributes.floating_network_id,
        'key_pair_name': attributes.keypair_name,
        'private_key_path': manager1.remote_private_key_path,
        'flavor': attributes.small_flavor_name,
        'network_name': attributes.network_name,
        'agent_user': attributes.centos7_username,
        'image': attributes.centos7_image_name
    }
    logger.info('Deploying helloworld on 4.0 manager..')

    manager1.client.blueprints.publish_archive(
        HELLO_WORLD_URL,
        blueprint_id,
        'openstack-blueprint.yaml',
        )
    manager1.client.deployments.create(
        blueprint_id,
        deployment_id,
        inputs,
        )
    manager1.client.deployments.list()
    manager1.client.executions.start(
        deployment_id,
        'install',
        )


@retrying.retry(stop_max_attempt_number=6, wait_fixed=5000)
def _assert_restore_workflow_terminated(execution_id, client, logger):
    logger.info('Getting restore workflow execution.. [id=%s]', execution_id)
    execution = client.executions.get(execution_id)
    logger.info('- execution.status = %s', execution.status)
    assert execution.status == 'terminated'
