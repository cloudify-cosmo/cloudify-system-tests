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
from cosmo_tester.framework.examples.hello_world import centos_hello_world

from cosmo_tester.test_suites.snapshots import (
    assert_snapshot_created,
    download_snapshot,
    upload_snapshot,
    restore_snapshot,
    delete_manager,
    verify_services_status
)


@pytest.fixture(scope='module')
def managers(cfy, ssh_key, module_tmpdir, attributes, logger):
    hosts = TestHosts(cfy, ssh_key, module_tmpdir, attributes, logger, 2)
    try:
        _managers = hosts.instances

        # The second manager needs to be clean, to allow restoring to it
        _managers[1].upload_plugins = False
        hosts.create()
        yield _managers
    finally:
        hosts.destroy()


@pytest.fixture(scope='function')
def hello(managers, cfy, ssh_key, tmpdir, attributes, logger):
    manager = managers[0]
    hw = centos_hello_world(cfy, manager, attributes, ssh_key, logger, tmpdir)
    yield hw
    if hw.cleanup_required:
        hw.cleanup()


def test_restore_snapshot_and_agents_install(
        managers, hello, cfy, logger, tmpdir
):
    local_snapshot_path = str(tmpdir / 'snapshot.zip')
    snapshot_id = 'snap'

    old_manager = managers[0]
    new_manager = managers[1]

    old_manager.use()

    hello.upload_and_verify_install()

    old_manager.client.snapshots.create(snapshot_id, False, True)
    assert_snapshot_created(old_manager, snapshot_id, None)
    download_snapshot(old_manager, local_snapshot_path, snapshot_id, logger)

    new_manager.use()

    upload_snapshot(new_manager, local_snapshot_path, snapshot_id, logger)
    restore_snapshot(new_manager, snapshot_id, cfy, logger)

    verify_services_status(new_manager)

    new_manager.use()
    cfy.agents.install(['--stop-old-agent'])

    delete_manager(old_manager, logger)
    hello.manager = new_manager
    hello.assert_webserver_running()
    hello.uninstall()
