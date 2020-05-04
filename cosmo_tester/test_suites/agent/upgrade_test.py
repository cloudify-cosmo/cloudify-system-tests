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

from cosmo_tester.framework import util
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.test_hosts import TestHosts as Hosts

from cosmo_tester.test_suites.snapshots import restore_snapshot

ATTRIBUTES = util.get_attributes()


@pytest.fixture(scope='module')
def managers_and_vm(cfy, ssh_key, module_tmpdir, attributes, logger):
    hosts = Hosts(cfy, ssh_key, module_tmpdir, attributes, logger, 3)
    try:
        managers = hosts.instances[:2]
        vm = hosts.instances[2]

        managers[0].upload_files = False
        managers[1].upload_files = False
        managers[0].restservice_expected = True
        managers[1].restservice_expected = True

        vm.upload_files = False
        vm.image_name = ATTRIBUTES['centos_7_image_name']
        vm.username = ATTRIBUTES['centos_7_username']

        hosts.create()
        yield hosts.instances
    finally:
        hosts.destroy()


@pytest.fixture(scope='function')
def example(managers_and_vm, cfy, ssh_key, tmpdir, attributes, logger):
    manager = managers_and_vm[0]
    vm = managers_and_vm[2]

    example = get_example_deployment(manager, ssh_key, logger,
                                     'agent_upgrade', vm)

    try:
        yield example
    finally:
        if example.installed:
            example.uninstall()


def test_old_agent_stopped_after_agent_upgrade(
        managers_and_vm, example, cfy, logger, tmpdir
):
    local_snapshot_path = str(tmpdir / 'snapshot.zip')
    snapshot_id = 'snap'

    old_manager, new_manager, vm = managers_and_vm

    old_manager.use()

    example.upload_and_verify_install()

    cfy.snapshots.create([snapshot_id])
    old_manager.wait_for_all_executions()
    cfy.snapshots.download([snapshot_id, '-o', local_snapshot_path])

    new_manager.use()

    cfy.snapshots.upload([local_snapshot_path, '-s', snapshot_id])
    restore_snapshot(new_manager, snapshot_id, cfy, logger)

    # Before upgrading the agents, the old agent should still be up
    old_manager.use()
    cfy.agents.validate('--tenant-name', example.tenant)

    # Upgrade to new agents and stop old agents
    new_manager.use()
    cfy.agents.install('--stop-old-agent',
                       '--tenant-name', example.tenant)

    logger.info('Validating the old agent is indeed down')
    _assert_agent_not_running(old_manager, vm, 'vm', example.tenant)
    old_manager.stop()

    new_manager.use()
    example.manager = new_manager
    example.check_files()
    example.uninstall()


def _assert_agent_not_running(manager, vm, node_name, tenant):
    with util.set_client_tenant(manager, tenant):
        node = manager.client.node_instances.list(node_id=node_name)[0]
    agent = node.runtime_properties['cloudify_agent']
    ssh_command = 'sudo service cloudify-worker-{name} status'.format(
        name=agent['name'],
    )
    response = vm.run_command(ssh_command, warn_only=True).stdout
    assert 'inactive' in response
