########
# Copyright (c) 2018 GigaSpaces Technologies Ltd. All rights reserved
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

from cosmo_tester.framework.test_hosts import TestHosts
from cosmo_tester.framework.examples.nodecellar import NodeCellarExample

from cosmo_tester.test_suites.snapshots import restore_snapshot


@pytest.fixture(scope='module')
def managers(cfy, ssh_key, module_tmpdir, attributes, logger):
    hosts = TestHosts(cfy, ssh_key, module_tmpdir, attributes, logger, 2)
    try:
        _managers = hosts.instances

        # The second manager needs to be clean, to allow restoring to it
        _managers[1].upload_plugins = False
        hosts.create()
        hosts.instances[0].upload_plugin(
            attributes['default_openstack_plugin']
        )
        yield _managers
    finally:
        hosts.destroy()


@pytest.fixture(scope='function')
def nodecellar(managers, cfy, ssh_key, tmpdir, attributes, logger):
    """
    Using nodecellar instead of hello world, because the process stays up
    after the old agent is stopped (as opposed to the webserver started in
    hello world)
    """
    manager = managers[0]
    nc = NodeCellarExample(cfy, manager, attributes, ssh_key, logger, tmpdir)
    nc.blueprint_file = 'openstack-blueprint.yaml'
    yield nc
    if nc.cleanup_required:
        nc.cleanup()


def test_old_agent_stopped_after_agent_upgrade(
        managers, nodecellar, cfy, logger, tmpdir
):
    local_snapshot_path = str(tmpdir / 'snapshot.zip')
    snapshot_id = 'snap'

    old_manager = managers[0]
    new_manager = managers[1]

    old_manager.use()

    nodecellar.upload_and_verify_install()

    cfy.snapshots.create([snapshot_id])
    old_manager.wait_for_all_executions()
    cfy.snapshots.download([snapshot_id, '-o', local_snapshot_path])

    new_manager.use()

    cfy.snapshots.upload([local_snapshot_path, '-s', snapshot_id])
    restore_snapshot(new_manager, snapshot_id, cfy, logger)

    # Before upgrading the agents, the old agent should still be up
    old_manager.use()
    cfy.agents.validate()

    # Upgrade to new agents and stop old agents
    new_manager.use()
    cfy.agents.install('--stop-old-agent')

    logger.info('Validating the old agent is indeed down')
    _assert_agent_not_running(old_manager, 'nodejs_host')
    old_manager.stop()

    new_manager.use()
    nodecellar.manager = new_manager
    nodecellar.verify_installation()
    nodecellar.uninstall()


def _assert_agent_not_running(manager, node_name):
    node = manager.client.node_instances.list(node_name=node_name)[0]
    agent = node.runtime_properties['cloudify_agent']
    ssh_command = ('sudo ssh -o StrictHostKeyChecking=no '
                   '{user}@{ip} -i {key} '
                   '"sudo service cloudify-worker-{name} status"'
                   .format(user=agent['user'],
                           ip=node.runtime_properties['ip'],
                           key=agent['key'],
                           name=agent['name']))
    with manager.ssh() as fabric:
        response = fabric.run(ssh_command, warn_only=True)
        assert('not running' in response)
