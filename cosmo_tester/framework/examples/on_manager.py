from cosmo_tester.framework.examples import AbstractExample
from cosmo_tester.framework import util


class OnManagerExample(AbstractExample):

    def __init__(self, cfy, manager, attributes, ssh_key, logger, tmpdir,
                 tenant, suffix=None):
        super(OnManagerExample, self).__init__(cfy, manager, attributes,
                                               ssh_key, logger, tmpdir,
                                               tenant=tenant)
        self.inputs = {
            'path': '/tmp/test_file',
            'content': 'Test',
        }
        self.blueprint_id = 'on_manager_example'
        if suffix:
            self.blueprint_id = self.blueprint_id + '-' + suffix
        self.deployment_id = self.blueprint_id

    def upload_blueprint(self):
        blueprint_file = util.get_resource_path(
            'blueprints/compute/example.yaml'
        )

        self.logger.info('Uploading blueprint: %s [id=%s]',
                         blueprint_file,
                         self.blueprint_id)
        with open(self.ssh_key.private_key_path) as key_handle:
            ssh_key = key_handle.read()

        with util.set_client_tenant(self.manager, self.tenant):
            self.manager.client.secrets.create(
                'agent_key',
                ssh_key,
            )
            self.manager.client.blueprints.upload(
                blueprint_file, self.blueprint_id)

    def check_files(self):
        instances = self.manager.client.node_instances.list(
            deployment_id=self.deployment_id,
            _include=['id', 'node_id'],
        )

        expected_content = self.inputs['content']
        for instance in instances:
            if instance.node_id == 'file':
                file_path = self.inputs['path'] + '_' + instance.id
                content = self.manager.get_remote_file_content(file_path)
                assert content == expected_content
