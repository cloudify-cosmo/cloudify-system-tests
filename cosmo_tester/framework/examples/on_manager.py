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
        self.blueprint_file = util.get_resource_path(
            'blueprints/compute/example.yaml'
        )

    def set_agent_key_secret(self):
        with open(self.ssh_key.private_key_path) as key_handle:
            ssh_key = key_handle.read()
        with util.set_client_tenant(self.manager, self.tenant):
            self.manager.client.secrets.create(
                'agent_key',
                ssh_key,
            )

    def upload_blueprint(self):
        self.logger.info('Uploading blueprint: %s [id=%s]',
                         self.blueprint_file,
                         self.blueprint_id)

        self.set_agent_key_secret()

        with util.set_client_tenant(self.manager, self.tenant):
            self.manager.client.blueprints.upload(
                self.blueprint_file, self.blueprint_id)

    def check_files(self, path=None, expected_content=None):
        instances = self.manager.client.node_instances.list(
            deployment_id=self.deployment_id,
            _include=['id', 'node_id'],
        )

        if path is None:
            path = self.inputs['path']
        if expected_content is None:
            expected_content = self.inputs['content']

        for instance in instances:
            if instance.node_id == 'file':
                file_path = path + '_' + instance.id
                content = self.manager.get_remote_file_content(file_path)
                assert content == expected_content

    def uninstall(self):
        self.logger.info('Cleaning up on manager example.')
        self.cfy.executions.start(
            '--deployment-id', self.deployment_id,
            '--tenant-name', self.tenant,
            'uninstall'
        )
        self.check_all_test_files_deleted()

    def check_all_test_files_deleted(self, path=None):
        if path is None:
            path = self.inputs['path']

        # This gets us the full paths, which then allows us to see if the test
        # file prefix is in there.
        # Technically this could collide if the string /tmp/test_file is in
        # there but not actually part of the path, but that's unlikely so
        # we'll tackle that problem when we cause it.
        # Running with sudo to avoid exit status of 1 due to root owned files
        tmp_contents = self.manager.run_command('sudo find /tmp').stdout
        assert path not in tmp_contents
