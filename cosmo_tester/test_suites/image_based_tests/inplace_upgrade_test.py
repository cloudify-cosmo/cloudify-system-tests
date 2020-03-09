########
# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
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

import os
from time import sleep
from os.path import join

import pytest

from cosmo_tester.framework import git_helper
from cosmo_tester.framework.test_hosts import TestHosts, get_image
from cosmo_tester.framework.examples.hello_world import get_hello_worlds
from cosmo_tester.framework.util import is_community

if is_community():
    VERSIONS = ['master']
else:
    VERSIONS = ['4.3.1', 'master']


@pytest.fixture(scope='module', params=VERSIONS)
def image_based_manager(request, cfy, ssh_key, module_tmpdir, attributes,
                        logger):
    instances = [get_image(request.param)]
    hosts = TestHosts(cfy, ssh_key, module_tmpdir, attributes, logger,
                      instances=instances, request=request)
    try:
        hosts.create()
        hosts.instances[0].use()
        yield hosts.instances[0]
    finally:
        hosts.destroy()


manager = image_based_manager


def test_inplace_upgrade(cfy,
                         manager,
                         attributes,
                         ssh_key,
                         module_tmpdir,
                         logger):
    snapshot_name = 'inplace_upgrade_snapshot_{0}'.format(manager.image_type)
    snapshot_path = join(str(module_tmpdir), snapshot_name) + '.zip'

    if manager.image_type == git_helper.MASTER_BRANCH:
        os.environ['BRANCH_NAME_CORE'] = manager.image_type
    else:
        os.environ['BRANCH_NAME_CORE'] = '{0}-build'.format(
            manager.image_type)

    # We can't use the hello_worlds fixture here because this test has
    # multiple managers rather than just one (the hosts vs a single
    # manager).
    hellos = get_hello_worlds(cfy, manager, attributes, ssh_key,
                              module_tmpdir, logger)
    for hello_world in hellos:
        hello_world.upload_and_verify_install()
    cfy.snapshots.create([snapshot_name])
    manager.wait_for_all_executions()
    cfy.snapshots.download([snapshot_name, '-o', snapshot_path])
    manager.teardown()
    with manager.ssh() as fabric_ssh:
        # The teardown doesn't properly clean up rabbitmq
        fabric_ssh.sudo('pkill -f rabbitmq')
        fabric_ssh.sudo('rm -rf /var/lib/rabbitmq')
    manager.bootstrap()
    manager.use()
    manager.upload_necessary_files()
    cfy.snapshots.upload([snapshot_path, '-s', snapshot_name])

    with manager.ssh() as fabric_ssh:
        # Perform the restore after opening the ssh session and don't wait for
        # the execution to finish to avoid a race condition that occasionally
        # causes test failures when we don't ssh in before the shutdown.
        cfy.snapshots.restore([snapshot_name, '--restore-certificates'])
        retry_delay = 1
        max_attempts = 240
        reboot_triggered = False
        reboot_performed = False
        for attempt in range(0, max_attempts):
            try:
                if fabric_ssh.run(
                    'ps aux | grep shutdown | grep -v grep || true'
                ).strip():
                    # Still waiting for post-restore reboot
                    sleep(retry_delay)
                    reboot_triggered = True
                    logger.info('Reboot trigger has been set.')
                    continue
                elif reboot_triggered:
                    reboot_performed = True
                    logger.info('Reboot has been performed, continuing.')
                    break
                else:
                    sleep(retry_delay)
            except Exception as err:
                if attempt == max_attempts - 1:
                    raise(err)
                sleep(retry_delay)
        if not reboot_triggered:
            log_tail = fabric_ssh.run(
                'sudo tail -n30 '
                '/var/log/cloudify/mgmtworker/logs/__system__.log'
            ).strip()
            raise RuntimeError(
                'Did not see reboot trigger. '
                'Did the manager already reboot?\n'
                'End of snapshot log:\n'
                '{log_tail}'.format(log_tail=log_tail)
            )
        if not reboot_performed:
            raise RuntimeError('Expected reboot did not happen.')

    # we need to give the agents enough time to reconnect to the manager;
    # celery retries with a backoff of up to 32 seconds
    sleep(50)
    manager.wait_for_manager()

    for hello_world in hellos:
        cfy.agents.install(['-t', hello_world.tenant])
        hello_world.uninstall()
        hello_world.delete_deployment()
