import random
import string
import time
import os

from cloudify_rest_client.executions import Execution

from cosmo_tester.framework.git_helper import clone
from cosmo_tester.framework.testenv import TestCase


class MultiManagerTest(TestCase):
    def _start_execution_and_wait(self, client, deployment, workflow_id,
                                  success_statuses, fail_statuses):
        client.executions.start(deployment, workflow_id)

        self._wait_for_execution(
            client, workflow_id, success_statuses, fail_statuses)

    def _wait_for_execution(self, client, workflow_id,
                            success_statuses, fail_statuses):
        while True:
            executions = client.executions.list(include_system_workflows=True)

            execution = next(e for e in executions
                             if e.workflow_id == workflow_id)

            if execution.status in success_statuses:
                break
            elif execution.status in fail_statuses:
                raise RuntimeError('{} failed.'.format(workflow_id))
            else:
                self.logger.info('Not yet...')

            time.sleep(15)

    def _create_snapshot(self, client, name):
        client.snapshots.create(name, False, False)

        while True:
            snapshots = client.snapshots.list()

            snapshot = next(s for s in snapshots if s.id == name)

            if snapshot.status == 'created':
                break
            else:
                self.logger.info('Not yet...')

            time.sleep(15)

    def _restore_snapshot(self, client, name):
        client.snapshots.restore(name)

        time.sleep(3)

        while True:
            executions = client.executions.list(include_system_workflows=True)

            execution = next(e for e in executions
                             if e.workflow_id == 'restore_snapshot')

            if execution.status in (Execution.TERMINATED, Execution.CANCELLED,
                                    Execution.FAILED):
                break
            else:
                self.logger.info('Not yet...')

            time.sleep(15)

    def test_create_snapshot_and_restore_on_another_manager(self):
        self.logger.info('Cloning nodecellar repo...')
        nodecellar_repo_dir = clone(self.repo_url, self.workdir)
        blueprint_path = nodecellar_repo_dir / 'openstack-blueprint.yaml'

        self.logger.info('Uploading blueprint...')
        self.client.blueprints.upload(blueprint_path, 'node')
        self.logger.info('Blueprint uploaded.')

        self.logger.info('Creating deployment...')
        self.client.deployments.create('node', 'node', self.get_inputs())
        self._wait_for_execution(
            self.client, 'create_deployment_environment',
            [Execution.TERMINATED], [Execution.CANCELLED, Execution.FAILED])
        self.logger.info('Deployment created.')

        self.logger.info('Installing...')
        self._start_execution_and_wait(
            self.client, 'node', 'install',
            [Execution.TERMINATED], [Execution.CANCELLED, Execution.FAILED])
        self.logger.info('Installed.')

        self.logger.info('Creating snapshot...')
        self._create_snapshot(self.client, 'node')
        self.logger.info('Snapshot created.')

        self.logger.info('Downloading snapshot...')
        snapshot_file_name = ''.join(random.choice(string.ascii_letters)
                                     for _ in xrange(10))
        snapshot_file_path = os.path.join('/tmp', snapshot_file_name)
        self.client.snapshots.download('node', snapshot_file_path)
        self.logger.info('Snapshot downloaded.')

        self.logger.info('Uploading snapshot to the second manager...')
        self.additional_clients[0].snapshots.upload(snapshot_file_path, 'node')
        # creating a snapshots is asynchronous, but it lasts a second or two...
        time.sleep(3)
        if os.path.isfile(snapshot_file_path):
            os.remove(snapshot_file_path)
        self.logger.info('Snapshot uploaded.')

        self.logger.info('Restoring snapshot...')
        self._restore_snapshot(self.additional_clients[0], 'node')
        self.logger.info('Snapshot restored (there is a chance, actually).')

        self.logger.info('Installing new agents...')
        self._start_execution_and_wait(
            self.additional_clients[0], 'node', 'install_new_agents',
            [Execution.TERMINATED], [Execution.CANCELLED, Execution.FAILED])
        self.logger.info('Installed new agents.')

        self.logger.info('Uninstalling...')
        self._start_execution_and_wait(
            self.additional_clients[0], 'node', 'uninstall',
            [Execution.TERMINATED], [Execution.CANCELLED, Execution.FAILED])
        self.logger.info('Uninstalled.')

    def get_inputs(self):
        return {
            'image': self.env.ubuntu_trusty_image_name,
            'flavor': self.env.medium_flavor_id,
            'agent_user': self.env.ubuntu_trusty_image_user
        }

    @property
    def repo_url(self):
        return 'https://github.com/cloudify-cosmo/' \
               'cloudify-nodecellar-example.git'
