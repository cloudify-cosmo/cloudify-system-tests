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

from cosmo_tester.framework.cluster import (
    CloudifyCluster,
    MANAGERS,
)
from cosmo_tester.framework.util import assert_snapshot_created

from . import (
    deployment_id,
    deploy_helloworld,
    wait_for_execution,
    update_client_tenant
)


@pytest.fixture(
        scope='module',
        params=['master', '4.0.1', '4.0', '3.4.2'])
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

    if request.param.startswith('3'):
        # Install dev tools & python headers
        with cluster.managers[1].ssh() as fabric_ssh:
            fabric_ssh.sudo('yum -y -q groupinstall "Development Tools"')
            fabric_ssh.sudo('yum -y -q install python-devel')

    yield cluster

    cluster.destroy()


@pytest.fixture(autouse=True)
def _hello_world_example(cluster, attributes, logger):
    manager0 = cluster.managers[0]
    deploy_helloworld(attributes, logger, manager0)

    yield

    if not manager0.deleted:
        try:
            logger.info('Cleaning up hello_world_example deployment...')
            execution = manager0.client.executions.start(
                deployment_id,
                'uninstall',
                parameters=(
                    None
                    if manager0.branch_name.startswith('3')
                    else {'ignore_failure': True}
                ),
                )
            wait_for_execution(
                manager0.client,
                execution,
                logger,
                )
        except Exception as e:
            logger.error('Error on test cleanup: %s', e)


def test_restore_snapshot_and_agents_upgrade(
        cfy, cluster, attributes, logger, tmpdir):
    manager0 = cluster.managers[0]
    manager1 = cluster.managers[1]

    snapshot_id = str(uuid.uuid4())

    logger.info('Creating snapshot on old manager..')
    manager0.client.snapshots.create(snapshot_id, False, False, False)
    assert_snapshot_created(manager0, snapshot_id, attributes)

    local_snapshot_path = str(tmpdir / 'snapshot.zip')

    logger.info('Downloading snapshot from old manager..')
    manager0.client.snapshots.list()
    manager0.client.snapshots.download(snapshot_id, local_snapshot_path)

    manager1.use()
    if '3.4' in manager0.branch_name:
        # When working with a 3.x snapshot, we need to create a new tenant
        # into which we'll restore the snapshot
        tenant_name = manager0.restore_tenant_name
        manager1.client.tenants.create(tenant_name)

        # Update the tenant in the manager's client and CLI
        update_client_tenant(manager1.client, tenant_name)
        cfy.profiles.set(['-t', tenant_name])

    logger.info('Uploading snapshot to latest manager..')
    snapshot = manager1.client.snapshots.upload(local_snapshot_path,
                                                snapshot_id)
    logger.info('Uploaded snapshot:%s%s',
                os.linesep,
                json.dumps(snapshot, indent=2))

    cfy.snapshots.list()

    logger.info('Restoring snapshot on latest manager..')
    restore_execution = manager1.client.snapshots.restore(snapshot_id)
    logger.info('Snapshot restore execution:%s%s',
                os.linesep,
                json.dumps(restore_execution, indent=2))

    cfy.executions.list(['--include-system-workflows'])

    restore_execution = wait_for_execution(
        manager1.client,
        restore_execution,
        logger)
    assert restore_execution.status == 'terminated'

    cfy.executions.list(['--include-system-workflows'])

    cfy.deployments.list()
    deployments = manager1.client.deployments.list()
    assert 1 == len(deployments)

    logger.info('Upgrading agents..')
    cfy.agents.install()

    logger.info('Deleting original {version} manager..'.format(
        version=manager0.branch_name))
    manager0.delete()

    logger.info('Uninstalling deployment from latest manager..')
    cfy.executions.start.uninstall(['-d', deployment_id])
    cfy.deployments.delete(deployment_id)
