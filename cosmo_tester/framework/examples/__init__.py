########
# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
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
import json
from abc import ABCMeta

import testtools

from cosmo_tester.framework import git_helper
from cosmo_tester.framework.util import (
    get_resource_path,
    prepare_and_get_test_tenant,
    set_client_tenant,
)


class BaseExample(object):

    def __init__(self, cfy, manager, ssh_key, logger,
                 blueprint_id, tenant='default_tenant'):
        self.logger = logger
        self.manager = manager
        self.cfy = cfy
        self.ssh_key = ssh_key
        self.tenant = tenant
        self.create_secret = True
        self.blueprint_file = get_resource_path(
            'blueprints/compute/example.yaml'
        )
        self.inputs = {
            'path': '/tmp/test_file',
            'content': 'Test',
        }
        self.blueprint_id = blueprint_id
        self.deployment_id = self.blueprint_id
        self.example_host = manager
        self.installed = False

    def set_agent_key_secret(self):
        with open(self.ssh_key.private_key_path) as key_handle:
            ssh_key = key_handle.read()
        with set_client_tenant(self.manager, self.tenant):
            self.manager.client.secrets.create(
                'agent_key',
                ssh_key,
            )

    def upload_blueprint(self):
        self.logger.info('Uploading blueprint: %s [id=%s]',
                         self.blueprint_file,
                         self.blueprint_id)

        if self.create_secret:
            self.set_agent_key_secret()

        with set_client_tenant(self.manager, self.tenant):
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
                content = self.example_host.get_remote_file_content(file_path)
                assert content == expected_content

    def uninstall(self, check_files_are_deleted=True):
        self.logger.info('Cleaning up example.')
        self.cfy.executions.start(
            '--deployment-id', self.deployment_id,
            '--tenant-name', self.tenant,
            'uninstall'
        )
        self.installed = False
        if check_files_are_deleted:
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
        tmp_contents = self.example_host.run_command('sudo find /tmp').stdout
        assert path not in tmp_contents

    def upload_and_verify_install(self, timeout=900):
        self.upload_blueprint()
        self.create_deployment()
        self.install(timeout)
        self.assert_deployment_events_exist()
        self.check_files()

    def create_deployment(self):
        self.logger.info(
                'Creating deployment [id=%s] with the following inputs:\n%s',
                self.deployment_id,
                json.dumps(self.inputs, indent=2))
        with set_client_tenant(self.manager, self.tenant):
            self.manager.client.deployments.create(
                deployment_id=self.deployment_id,
                blueprint_id=self.blueprint_id,
                inputs=self.inputs)
        self.cfy.deployments.list(tenant_name=self.tenant)

    def install(self, timeout=900):
        self.logger.info('Installing deployment...')
        try:
            self.cfy.executions.start.install(['-d', self.deployment_id,
                                               '-t', self.tenant,
                                               '--timeout', timeout])
            self.installed = True
        except Exception as err:
            self.logger.error('Error on deployment execution: %s', err)
            self.logger.info('Listing executions..')
            self.cfy.executions.list(['--all-tenants',
                                      '--include-system-workflows'])
            raise

    def assert_deployment_events_exist(self):
        self.logger.info('Verifying deployment events..')
        with set_client_tenant(self.manager, self.tenant):
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


class OnManagerExample(BaseExample):

    def __init__(self, cfy, manager, ssh_key, logger, tenant):
        super(OnManagerExample, self).__init__(
            cfy, manager, ssh_key, logger,
            blueprint_id='on_manager_example', tenant=tenant,
        )


class OnVMExample(BaseExample):

    def __init__(self, cfy, manager, vm, ssh_key, logger, tenant):
        super(OnVMExample, self).__init__(
            cfy, manager, ssh_key, logger,
            blueprint_id='on_vm_example', tenant=tenant,
        )
        self.inputs['server_ip'] = vm.ip_address
        self.example_host = vm


def get_example_deployment(cfy, manager, ssh_key, logger, tenant_name,
                           vm=None, upload_plugin=True):
    tenant = prepare_and_get_test_tenant(tenant_name, manager, cfy,
                                         upload=False)

    if upload_plugin:
        manager.upload_test_plugin(tenant)

    if vm:
        return OnVMExample(cfy, manager, vm, ssh_key, logger, tenant)
    else:
        return OnManagerExample(cfy, manager, ssh_key, logger, tenant)


class AbstractExample(testtools.TestCase):

    __metaclass__ = ABCMeta

    REPOSITORY_URL = None

    def __init__(self, cfy, manager, attributes, ssh_key, logger, tmpdir,
                 branch=None, tenant='default_tenant', suffix=''):
        self.attributes = attributes
        self.logger = logger
        self.manager = manager
        self.cfy = cfy
        self.tmpdir = tmpdir
        self.branch = branch
        self._ssh_key = ssh_key
        self._cleanup_required = False
        self._blueprint_file = None
        self._inputs = None
        self._cloned_to = None
        self.blueprint_id = 'hello-{suffix}'.format(suffix=suffix)
        self.deployment_id = self.blueprint_id
        self.skip_plugins_validation = False
        self.tenant = tenant
        self.suffix = suffix

    @property
    def blueprint_file(self):
        if not self._blueprint_file:
            raise ValueError('blueprint_file not set')
        return self._blueprint_file

    @blueprint_file.setter
    def blueprint_file(self, value):
        self._blueprint_file = value

    @property
    def blueprint_path(self):
        if not self._cloned_to:
            raise RuntimeError('_cloned_to is not set')
        return self._cloned_to / self.blueprint_file

    @property
    def cleanup_required(self):
        return self._cleanup_required

    @property
    def outputs(self):
        with set_client_tenant(self.manager, self.tenant):
            outputs = self.manager.client.deployments.outputs.get(
                self.deployment_id,
            )['outputs']
        self.logger.info('Deployment outputs: %s%s',
                         os.linesep, json.dumps(outputs, indent=2))
        return outputs

    def verify_all(self):
        self.upload_blueprint()
        self.create_deployment()
        self.install()
        self.verify_installation()
        self.uninstall()
        self.delete_deployment()

    def verify_installation(self):
        self.assert_deployment_events_exist()

    def upload_and_verify_install(self, timeout=900):
        self.upload_blueprint()
        self.create_deployment()
        self.install(timeout)
        self.verify_installation()

    def delete_deployment(self, use_cfy=False):
        self.logger.info('Deleting deployment: {0}'.format(self.deployment_id))
        if use_cfy:
            self.cfy.profile.set([
                '-t', self.tenant,
            ])
            self.cfy.deployments.delete(self.deployment_id)
        else:
            with set_client_tenant(self.manager, self.tenant):
                self.manager.client.deployments.delete(
                    self.deployment_id,
                )

    def uninstall(self, timeout=900):
        self.logger.info('Uninstalling deployment...')
        self.cfy.executions.start.uninstall(['-d', self.deployment_id,
                                             '-t', self.tenant,
                                             '--timeout', timeout])
        self._cleanup_required = False

    def _patch_blueprint(self):
        """ A method that add the ability to patch the blueprint if needed """
        pass

    def upload_blueprint(self, use_cfy=False):
        self.clone_example()
        blueprint_file = self._cloned_to / self.blueprint_file
        self._patch_blueprint()

        self.logger.info('Uploading blueprint: %s [id=%s]',
                         blueprint_file,
                         self.blueprint_id)
        if use_cfy:
            self.cfy.profile.set([
                '-t', self.tenant,
            ])
            self.cfy.blueprint.upload([
                '-b', self.blueprint_id,
                blueprint_file
            ])
        else:
            with set_client_tenant(self.manager, self.tenant):
                self.manager.client.blueprints.upload(
                    blueprint_file, self.blueprint_id)

    def delete_blueprint(self, use_cfy=False):
        self.logger.info('Deleting blueprint: {0}'.format(self.blueprint_id))
        if use_cfy:
            self.cfy.profile.set([
                '-t', self.tenant,
            ])
            self.cfy.blueprint.delete(self.blueprint_id)
        else:
            with set_client_tenant(self.manager, self.tenant):
                self.manager.client.blueprints.delete(self.blueprint_id)

    def create_deployment(self):
        self.logger.info(
                'Creating deployment [id=%s] with the following inputs:%s%s',
                self.deployment_id,
                os.linesep,
                json.dumps(self.inputs, indent=2))
        with set_client_tenant(self.manager, self.tenant):
            self.manager.client.deployments.create(
                deployment_id=self.deployment_id,
                blueprint_id=self.blueprint_id,
                inputs=self.inputs,
                skip_plugins_validation=self.skip_plugins_validation)
        self.cfy.deployments.list(tenant_name=self.tenant)

    def install(self, timeout=900):
        self.logger.info('Installing deployment...')
        self._cleanup_required = True
        try:
            self.cfy.executions.start.install(['-d', self.deployment_id,
                                               '-t', self.tenant,
                                               '--timeout', timeout])
        except Exception as e:
            if 'if there is a running system-wide' in e.message:
                self.logger.error('Error on deployment execution: %s', e)
                self.logger.info('Listing executions..')
                self.cfy.executions.list(['-d', self.deployment_id])
                self.cfy.executions.list(['--include-system-workflows'])
            raise

    def clone_example(self):
        if not self._cloned_to:
            # Destination will be e.g.
            # /tmp/pytest_generated_tempdir_for_test_1/examples/bootstrap_ssl/
            destination = os.path.join(
                str(self.tmpdir), 'examples', self.suffix,
            )

            self.branch = self.branch or os.environ.get(
                'BRANCH_NAME_CORE',
                git_helper.MASTER_BRANCH)

            self._cloned_to = git_helper.clone(self.REPOSITORY_URL,
                                               destination,
                                               self.branch)

    def cleanup(self, allow_custom_params=False):
        if self._cleanup_required:
            self.logger.info('Performing hello world cleanup..')
            params = ['-d', self.deployment_id, '-p',
                      'ignore_failure=true', '-f',
                      '-t', self.tenant]
            if allow_custom_params:
                params.append('--allow-custom-parameters')
            self.cfy.executions.start.uninstall(params)

    def assert_deployment_events_exist(self):
        self.logger.info('Verifying deployment events..')
        with set_client_tenant(self.manager, self.tenant):
            executions = self.manager.client.executions.list(
                deployment_id=self.deployment_id,
            )
            events = self.manager.client.events.list(
                execution_id=executions[0].id,
                _offset=0,
                _size=100,
                _sort='@timestamp',
            ).items
        self.assertGreater(len(events), 0,
                           'There are no events for deployment: {0}'.format(
                                   self.deployment_id))

    @property
    def ssh_key(self):
        return self._ssh_key
