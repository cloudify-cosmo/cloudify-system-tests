
import yaml
import requests
from retrying import retry

from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.test_suites.test_blueprints.hello_world_bash_test import \
    clone_hello_world


class DeploymentUpdateTest(TestCase):

    def deployment_update_test(self):

        self.dep_id = 'hello_world'
        self.initial_web_server_port = '8080'
        self.modified_web_server_port = '9090'

        self.upload_blueprint_and_deploy(
            deployment_id=self.dep_id,
            inputs={'webserver_port': self.initial_web_server_port,
                    'agent_user': self.env.agent_user,
                    'image': self.env.centos_7_image_id,
                    'flavor': self.env.medium_flavor_id}
            # for aws
            #  'image_id': self.env.ubuntu_trusty_image_id,
            #  'instance_type': self.env.medium_instance_type}
        )

        self.check_webserver()

        self.update_deployment(
            inputs={'webserver_port': self.modified_web_server_port})

        self.check_webserver(assert_online=False)

        self.revert_deployment(
            inputs={'webserver_port': self.initial_web_server_port})

        self.check_webserver()

        # self.assert_deployment_update_changes()

    def check_webserver(self, assert_online=True):
        outputs = self.client.deployments.outputs.get(self.dep_id)['outputs']
        self.logger.info('Deployment outputs: {0}'.format(outputs))
        self.logger.info('Verifying web server is running on: {0}'.format(
            outputs['http_endpoint']))
        self.verify_webserver_running(outputs['http_endpoint'], assert_online)

    @retry(stop_max_attempt_number=10, wait_fixed=5000)
    def verify_webserver_running(self, http_endpoint, assert_online=True):
        server_response = requests.get(http_endpoint, timeout=15)
        if assert_online:
            if server_response.status_code != 200:
                raise AssertionError('Unexpected status code: {}'
                                     .format(server_response.status_code))
        elif server_response.status_code == 200:
                raise AssertionError('Unexpected status code: {}'
                                     .format(server_response.status_code))

    def upload_blueprint_and_deploy(self,
                                    deployment_id=None,
                                    blueprint_file='blueprint.yaml',
                                    inputs=None):
        self.repo_dir = clone_hello_world(self.workdir)
        self.blueprint_yaml = self.repo_dir / blueprint_file
        self.upload_deploy_and_execute_install(
            deployment_id=deployment_id,
            fetch_state=False,
            inputs=inputs)

    def revert_deployment(self, inputs=None):
        self.cfy.update_deployment(self._deployment_id,
                                   self.blueprint_yaml,
                                   inputs=inputs)

    def _modify_blueprint(self, blueprint_path):
        blueprint = \
            self._remove_web_server_node(blueprint_path)
        with open(blueprint_path, 'w') as f:
            yaml.dump(blueprint_path, f)
        return blueprint

    def _remove_web_server_node(self, blueprint_path):
        with open(blueprint_path, 'r') as f:
            blueprint = yaml.load(f)

        del blueprint['node_templates']['http_web_server']
        return blueprint

    def update_deployment(self, inputs=None):
        modified_blueprint_path = self.copy_blueprint(self._modification_dir)
        self.modified_blueprint_yaml = \
            self._modify_blueprint(modified_blueprint_path)
        #
        # self.modified_blueprint_yaml = \
        #     modified_blueprint_path / self._modification_blueprint

        self.cfy.update_deployment(self._deployment_id,
                                   modified_blueprint_path,
                                   inputs=inputs)

    def assert_deployment_update_changes(self):
        pass
