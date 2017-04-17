from cosmo_tester.framework.git_helper import clone
from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.util import YamlPatcher
from cosmo_tester.test_suites.test_blueprints.hello_world_bash_test import (
    verify_webserver_running)

CLOUDIFY_HELLO_WORLD_EXAMPLE_URL = "https://github.com/cloudify-cosmo/" \
                                   "cloudify-hello-world-example.git"


class ScaleFrom0To1To0(TestCase):
    def setUp(self):
        super(ScaleFrom0To1To0, self).setUp()

        self.repo_dir = clone(CLOUDIFY_HELLO_WORLD_EXAMPLE_URL, self.workdir)
        self.blueprint_yaml = self.repo_dir / 'blueprint.yaml'
        self._patch_blueprint()

    def test_scale_from_0_to_1_to_0(self):
        self.upload_deploy_and_execute_install(inputs={
            'image': self.env.ubuntu_image_id,
            'flavor': self.env.flavor_name,
            'agent_user': self.env.cloudify_agent_user
        })

        self._assert_no_hello_world_vm()

        self.logger.info('Scaling with delta=1...')
        scale_to_1_exec = self.client.executions.start(
            self.test_id, 'scale', {'node_id': 'vm', 'delta': 1})
        self.wait_for_execution(scale_to_1_exec, 1000)
        self.logger.info('Finished scaling with delta=1.')

        self._assert_hello_world_vm_is_running()

        self.logger.info('Scaling with delta=-1...')
        scale_to_0_exec = self.client.executions.start(
            self.test_id, 'scale', {'node_id': 'vm', 'delta': -1})
        self.wait_for_execution(scale_to_0_exec, 1000)
        self.logger.info('Finished scaling with delta=-1...')

        self._assert_no_hello_world_vm()

        self.execute_uninstall()

    def _patch_blueprint(self):
        with YamlPatcher(self.blueprint_yaml) as patch:
            patch.merge_obj(
                'node_templates.vm',
                {'instances': {'deploy': 0}}
            )

    def _assert_no_hello_world_vm(self):
        vm = self.client.nodes.get(self.test_id, 'vm')
        self.assertEqual(vm.number_of_instances, 0)

    def _assert_hello_world_vm_is_running(self):
        vm = self.client.nodes.get(self.test_id, 'vm')
        self.assertEqual(vm.number_of_instances, 1)

        outputs = self.client.deployments.outputs.get(self.test_id)['outputs']
        verify_webserver_running(outputs['http_endpoint'])
