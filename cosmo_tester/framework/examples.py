import os
import json

from cosmo_tester.framework.util import (
    create_deployment,
    get_resource_path,
    prepare_and_get_test_tenant,
    set_client_tenant,
    wait_for_execution,
)


class BaseExample(object):
    def __init__(self, manager, ssh_key, logger,
                 blueprint_id, tenant='default_tenant',
                 using_agent=True):
        self.logger = logger
        self.manager = manager
        self.ssh_key = ssh_key
        self.tenant = tenant
        self.inputs = {
            'content': 'Test',
        }
        if using_agent:
            self.create_secret = True
            self.blueprint_file = get_resource_path(
                'blueprints/compute/example.yaml'
            )
            self.inputs['agent_user'] = manager.username
        else:
            self.create_secret = False
            self.blueprint_file = get_resource_path(
                'blueprints/compute/central_executor.yaml'
            )
        self.blueprint_id = blueprint_id
        self.deployment_id = self.blueprint_id
        self.example_host = manager
        self.installed = False
        self.windows = False

    def set_agent_key_secret(self):
        with open(self.ssh_key.private_key_path) as key_handle:
            ssh_key = key_handle.read()
        with set_client_tenant(self.manager.client, self.tenant):
            self.manager.client.secrets.create(
                'agent_key',
                ssh_key,
            )

    def use_windows(self, user, password):
        self.inputs['agent_port'] = '5985'
        self.inputs['os_family'] = 'windows'
        self.inputs['agent_password'] = password
        self.inputs['path'] = 'c:\\users\\{}\\test_file'.format(
            self.inputs['agent_user'],
        )
        self.windows = True

    def upload_blueprint(self):
        self.logger.info('Uploading blueprint: %s [id=%s]',
                         self.blueprint_file,
                         self.blueprint_id)

        if self.create_secret:
            self.set_agent_key_secret()

        with set_client_tenant(self.manager.client, self.tenant):
            self.manager.client.blueprints.upload(
                self.blueprint_file, self.blueprint_id)

    def create_deployment(self, skip_plugins_validation=False, wait=True):
        if 'path' not in self.inputs:
            self.inputs['path'] = '/home/{user}/test_file'.format(
                user=self.example_host.username,
            )
        self.logger.info(
                'Creating deployment [id=%s] with the following inputs:\n%s',
                self.deployment_id,
                json.dumps(self.inputs, indent=2))
        with set_client_tenant(self.manager.client, self.tenant):
            create_deployment(
                self.manager.client, self.blueprint_id, self.deployment_id,
                self.logger, inputs=self.inputs,
                skip_plugins_validation=skip_plugins_validation,
            )
            self.logger.info('Deployments for tenant {}'.format(self.tenant))
            for deployment in self.manager.client.deployments.list():
                self.logger.info(deployment['id'])
        if wait:
            self.wait_for_deployment_environment_creation()

    def wait_for_deployment_environment_creation(self):
        self.logger.info('Waiting for deployment env creation.')
        while True:
            with set_client_tenant(self.manager.client, self.tenant):
                executions = self.manager.client.executions.list(
                    _include=['status'],
                    deployment_id=self.deployment_id,
                    workflow_id='create_deployment_environment',
                )
                if all(exc['status'] == 'terminated' for exc in executions):
                    break
        self.logger.info('Deployment env created.')

    def install(self):
        self.logger.info('Installing deployment...')
        self.execute('install')
        self.installed = True

    def uninstall(self, check_files_are_deleted=True):
        self.logger.info('Cleaning up example.')
        self.execute('uninstall')
        self.installed = False
        if check_files_are_deleted:
            self.check_all_test_files_deleted()

    def execute(self, workflow_id, parameters=None):
        self.logger.info('Starting workflow: {}'.format(workflow_id))
        try:
            with set_client_tenant(self.manager.client, self.tenant):
                execution = self.manager.client.executions.start(
                    deployment_id=self.deployment_id,
                    workflow_id=workflow_id,
                    parameters=parameters,
                )
                wait_for_execution(self.manager.client, execution,
                                   self.logger)
        except Exception as err:
            self.logger.error('Error on deployment execution: %s', err)
            raise

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
                if self.windows:
                    data = self.example_host.get_windows_remote_file_content(
                        file_path)
                else:
                    data = self.example_host.get_remote_file_content(
                        file_path)
                assert data == expected_content

    def check_all_test_files_deleted(self, path=None):
        if path is None:
            path = self.inputs['path']

        # This gets us the full paths, which then allows us to see if the test
        # file prefix is in there.
        # Technically this could collide if the string /tmp/test_file is in
        # there but not actually part of the path, but that's unlikely so
        # we'll tackle that problem when we cause it.
        # Running with sudo to avoid exit status of 1 due to root owned files
        if self.windows:
            list_path = path.rsplit('\\', 1)[0]
            assert path
            tmp_contents = self.example_host.run_windows_command(
                'dir {}'.format(list_path)).std_out
        else:
            list_path = os.path.dirname(path)
            tmp_contents = self.example_host.run_command(
                'sudo find {}'.format(list_path)).stdout
        assert path not in tmp_contents

    def assert_deployment_events_exist(self):
        self.logger.info('Verifying deployment events..')
        with set_client_tenant(self.manager.client, self.tenant):
            executions = self.manager.client.executions.list(
                deployment_id=self.deployment_id,
            )
            events = self.manager.client.events.list(
                execution_id=executions[0].id,
                _offset=0,
                _size=100,
                _sort='@timestamp',
            ).items
        assert len(events) > 0, (
            'There are no events for deployment: {0}'.format(
                self.deployment_id,
            )
        )

    def upload_and_verify_install(self, skip_plugins_validation=False):
        self.upload_blueprint()
        self.create_deployment(skip_plugins_validation)
        self.install()
        self.assert_deployment_events_exist()
        self.check_files()


class OnManagerExample(BaseExample):
    def __init__(self, manager, ssh_key, logger, tenant,
                 using_agent=True):
        super(OnManagerExample, self).__init__(
            manager, ssh_key, logger,
            blueprint_id='on_manager_example', tenant=tenant,
            using_agent=using_agent,
        )


class OnVMExample(BaseExample):
    def __init__(self, manager, vm, ssh_key, logger, tenant,
                 using_agent=True):
        super(OnVMExample, self).__init__(
            manager, ssh_key, logger,
            blueprint_id='on_vm_example', tenant=tenant,
            using_agent=using_agent,
        )
        self.inputs['server_ip'] = vm.ip_address
        self.inputs['agent_user'] = vm.username
        self.example_host = vm


def get_example_deployment(manager, ssh_key, logger, tenant_name, test_config,
                           vm=None, upload_plugin=True, using_agent=True):
    tenant = prepare_and_get_test_tenant(tenant_name, manager, test_config)

    if upload_plugin:
        manager.upload_test_plugin(tenant)

    if vm:
        return OnVMExample(manager, vm, ssh_key, logger, tenant,
                           using_agent=using_agent)
    else:
        return OnManagerExample(manager, ssh_key, logger, tenant,
                                using_agent=using_agent)
