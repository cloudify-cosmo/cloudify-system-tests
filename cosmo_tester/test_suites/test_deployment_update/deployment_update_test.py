
from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.test_suites.test_blueprints.hello_world_bash_test import \
    clone_hello_world


class DeploymentUpdateTest(TestCase):

    def deployment_update_test(self):

        self.upload_blueprint_and_deploy()
        self.update_deployment()
        self.assert_deployment_update_changes()

    def upload_blueprint_and_deploy(self,
                                    blueprint_file='blueprint.yaml',
                                    inputs=None):
        self.repo_dir = clone_hello_world(self.workdir)
        self.blueprint_yaml = self.repo_dir / blueprint_file
        self.upload_deploy_and_execute_install(
                fetch_state=False,
                inputs=inputs)

    def update_deployment(self, inputs=None):
        modified_blueprint_path = self.copy_blueprint(self._modification_dir)

        self.modified_blueprint_yaml = \
            modified_blueprint_path / self._modification_blueprint

        self.cfy.update_deployment(self._deployment_id,
                                   self.modified_blueprint_yaml,
                                   inputs=inputs)

    def assert_deployment_update_changes(self):
        pass
