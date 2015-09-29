import json
import random
import string
import time
import os

from cloudify_rest_client.executions import Execution
import requests
from requests.exceptions import RequestException

from cosmo_tester.framework.git_helper import clone
from cosmo_tester.framework.testenv import TestCase


class MultiManagerTest(TestCase):
    """
    This test bootstraps managers, installs nodecellar using the first manager,
    checks whether it was installed correctly, creates a snapshot, downloads it,
    uploads it to the second manager, uninstalls nodecellar using the second
    manager, checks whether nodecellar is actually not running and tears down
    those managers.

    It is required that there is at least one additional manager defined
    in handler configuration.
    """
    repo_url = ('https://github.com/cloudify-cosmo/'
                'cloudify-nodecellar-example.git')
    nodecellar_nodejs_port = 8080

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
        client.snapshots.restore(name, True)

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

    def _get_nodecellar_inputs(self):
        return {
            'image': self.env.ubuntu_trusty_image_id,
            'flavor': self.env.medium_flavor_id,
            'agent_user': self.env.ubuntu_trusty_image_user
        }

    def _get_nodecellar_public_ip(self):
        for node in self.get_manager_state()['deployment_nodes']['node']:
            if node['node_id'].startswith('nodecellar_ip'):
                return node['runtime_properties'].get(
                    'floating_ip_address', None)
        return None

    def _assert_nodecellar_running(self, ip):
        if not ip:
            self.fail('There was no floating ip assigned to nodejs server.')

        nodejs_server_page_response = requests.get(
            'http://{0}:{1}'.format(ip, self.nodecellar_nodejs_port))
        self.assertEqual(200, nodejs_server_page_response.status_code,
                         'Failed to get home page of nodecellar app')
        page_title = 'Node Cellar'
        self.assertTrue(page_title in nodejs_server_page_response.text,
                        'Expected to find {0} in web server response: {1}'
                        .format(page_title, nodejs_server_page_response))

        wines_page_response = requests.get(
            'http://{0}:{1}/wines'.format(ip, self.nodecellar_nodejs_port))
        self.assertEqual(200, wines_page_response.status_code,
                         'Failed to get the wines page on nodecellar app ('
                         'probably means a problem with the connection to '
                         'MongoDB)')

        try:
            wines_json = json.loads(wines_page_response.text)
            if type(wines_json) != list:
                self.fail('Response from wines page is not a JSON list: {0}'
                          .format(wines_page_response.text))

            self.assertGreater(len(wines_json), 0,
                               'Expected at least 1 wine data in nodecellar '
                               'app; json returned on wines page is: {0}'
                               .format(wines_page_response.text))
        except ValueError:
            self.fail('Response from wines page is not a valid JSON: {0}'
                      .format(wines_page_response.text))

        self.logger.info('Nodecellar is running properly.')

    def _assert_nodecellar_not_running(self, ip):
        with self.assertRaises(RequestException):
            requests.get('http://{}:{}'.format(ip, self.nodecellar_nodejs_port),
                         timeout=5)
            self.logger.info('Nodecellar was uninstalled properly.')

    def test_create_snapshot_and_restore_on_another_manager(self):
        self.logger.info('Cloning nodecellar repo...')
        nodecellar_repo_dir = clone(self.repo_url, self.workdir, '3.3m5-build')
        blueprint_path = nodecellar_repo_dir / 'openstack-blueprint.yaml'

        self.logger.info('Uploading blueprint...')
        self.client.blueprints.upload(blueprint_path, 'node')
        self.logger.info('Blueprint uploaded.')

        self.logger.info('Creating deployment...')
        self.client.deployments.create('node', 'node',
                                       self._get_nodecellar_inputs())
        self._wait_for_execution(
            self.client, 'create_deployment_environment',
            [Execution.TERMINATED], [Execution.CANCELLED, Execution.FAILED])
        self.logger.info('Deployment created.')

        self.logger.info('Installing...')
        self._start_execution_and_wait(
            self.client, 'node', 'install',
            [Execution.TERMINATED], [Execution.CANCELLED, Execution.FAILED])
        self.logger.info('Installed.')

        nodejs_ip = self._get_nodecellar_public_ip()
        self._assert_nodecellar_running(nodejs_ip)

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
        self.logger.info('Snapshot uploaded.')

        self.logger.info('Removing snapshot file...')
        if os.path.isfile(snapshot_file_path):
            os.remove(snapshot_file_path)
        self.logger.info('Snapshot file removed.')

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

        self._assert_nodecellar_not_running(nodejs_ip)
