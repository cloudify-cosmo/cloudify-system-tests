########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
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
import shutil
import logging
import tempfile
from contextlib import contextmanager

import sh
import yaml
import requests
from path import path

# from cloudify_cli.utils import (load_cloudify_working_dir_settings,
#                                 get_configuration_path,
#                                 update_wd_settings)
from cloudify_cli.config.config import CLOUDIFY_CONFIG_PATH
from cloudify_cli.env import get_profile_context
from cosmo_tester.framework.util import (sh_bake,
                                         YamlPatcher,
                                         download_file)


# cfy = sh_bake(sh.cfy)
cfy_out = sh.cfy


DEFAULT_EXECUTE_TIMEOUT = 1800
INPUTS = 'inputs'
PARAMETERS = 'parameters'


def get_cfy(
        manager_ip=None,
        manager_user=None,
        manager_key=None,
        manager_port='22'
):
    cfy = sh_bake(sh.cfy)
    if manager_ip is not None:
        cfy.use(
            manager_ip,
            manager_user=manager_user,
            manager_key=manager_key,
            manager_port=manager_port
        )

    return cfy


def get_manager_ip():
        return get_profile_context().manager_ip


def get_provider_context():
    return get_profile_context().provider_context


class CfyHelper(object):

    def __init__(self,
                 # cfy_workdir=None,
                 manager_ip=None,
                 manager_user=None,
                 manager_key=None,
                 manager_port='22'):
        self.logger = logging.getLogger('TESTENV')
        self.logger.setLevel(logging.INFO)
        # self._cfy_workdir = cfy_workdir
        # self.tmpdir = False
        # if cfy_workdir is None:
        #     self.tmpdir = True
        #     self._cfy_workdir = tempfile.mkdtemp(prefix='cfy-')
        # self.workdir = path(self._cfy_workdir)
        self._cli = sh_bake(sh.cfy)
        if manager_ip is not None:
            self._cli.use(
                manager_ip,
                manager_user=manager_user,
                manager_key=manager_key,
                manager_port=manager_port
            )
            # self.use(manager_ip)
            # if manager_user and manager_key and manager_port:
            #     try:
            #         self._set_management_creds(manager_user, manager_key,
            #                                    manager_port)
            #     except Exception as ex:
            #         self.logger.warn(
            #             'Failed to set management creds. Note that you will '
            #             'not be able to perform ssh actions after bootstrap. '
            #             'Reason: {0}'.format(ex))

    def bootstrap(self, *args, **kwargs):
        self._cli.bootstrap(*args, **kwargs).wait()

    def _bootstrap(self,
                  blueprint_path,
                  inputs_file=None,
                  install_plugins=True,
                  keep_up_on_failure=False,
                  validate_only=False,
                  reset_context=False,
                  task_retries=5,
                  task_retry_interval=90,
                  subgraph_retries=2,
                  verbose=False,
                  debug=False):
        # cfy.init(reset_context=reset_context).wait()
        #
        # # with YamlPatcher(CLOUDIFY_CONFIG_PATH) as patch:
        # #     prop_path = ('local_provider_context.'
        # #                  'cloudify.workflows.subgraph_retries')
        # #     patch.set_value(prop_path, subgraph_retries)
        #
        # if not inputs_file:
        #     inputs_file = self._get_inputs_in_temp_file({}, 'manager')
        #
        cfy.bootstrap(
            blueprint_path,
            inputs=inputs_file,
            install_plugins=install_plugins,
            keep_up_on_failure=keep_up_on_failure,
            validate_only=validate_only,
            task_retries=task_retries,
            task_retry_interval=task_retry_interval,
            verbose=verbose,
            debug=debug).wait()

        if not validate_only:
            self.upload_plugins()

    def _download_wagons(self):
        self.logger.info('Downloading Wagons...')

        wagon_paths = []

        plugin_urls_location = (
            'https://raw.githubusercontent.com/cloudify-cosmo/'
            'cloudify-versions/{branch}/packages-urls/plugin-urls.yaml'.format(
                branch=os.environ.get('BRANCH_NAME_CORE', 'master'),
            )
        )

        plugins = yaml.load(
            requests.get(plugin_urls_location).text
        )['plugins']
        for plugin in plugins:
            self.logger.info(
                'Downloading: {0}...'.format(plugin['wgn_url'])
            )
            wagon_paths.append(
                download_file(plugin['wgn_url'])
            )
        return wagon_paths

    def upload_plugins(self):
        downloaded_wagon_paths = self._download_wagons()
        for wagon in downloaded_wagon_paths:
            with self.workdir:
                self.logger.info('Uploading {0}'.format(wagon))
                upload = cfy.plugins.upload(p=wagon, verbose=True)
                upload.wait()

    def recover(self, snapshot_path, task_retries=5):
        with self.workdir:
            cfy.recover(force=True,
                        task_retries=task_retries,
                        snapshot_path=snapshot_path).wait()

    def create_snapshot(self,
                        snapshot_id,
                        include_metrics=False,
                        exclude_credentials=False):
        with self.workdir:
            cfy.snapshots.create(
                snapshot_id=snapshot_id,
                include_metrics=include_metrics,
                exclude_credentials=exclude_credentials).wait()

    def download_snapshot(self, snapshot_id, output_path=''):

        with self.workdir:
            cfy.snapshots.download(
                snapshot_id=snapshot_id,
                output=output_path).wait()

    def teardown(self,
                 ignore_deployments=True,
                 verbose=False):
        with self.workdir:
            cfy.teardown(
                ignore_deployments=ignore_deployments,
                force=True,
                verbose=verbose).wait()

    def uninstall(self, deployment_id, workflow_id, parameters,
                  allow_custom_parameters, timeout, include_logs):

        parameters = self._get_parameters_in_temp_file(parameters, workflow_id)

        with self.workdir:
            cfy.uninstall(deployment_id=deployment_id,
                          workflow=workflow_id,
                          parameters=parameters,
                          allow_custom_parameters=allow_custom_parameters,
                          timeout=timeout,
                          include_logs=include_logs
                          ).wait()

    def install(
            self,
            blueprint_path,
            blueprint_id,
            deployment_id,
            verbose=False,
            include_logs=True,
            execute_timeout=DEFAULT_EXECUTE_TIMEOUT,
            inputs=None):

        inputs_file = self._get_inputs_in_temp_file(inputs, deployment_id)

        with self.workdir:
            cfy.install(blueprint_path=blueprint_path,
                        blueprint_id=blueprint_id,
                        deployment_id=deployment_id,
                        inputs=inputs_file,
                        timeout=execute_timeout,
                        include_logs=include_logs,
                        verbose=verbose).wait()

    upload_deploy_and_execute_install = install

    def publish_archive(self,
                        blueprint_id,
                        archive_location,
                        verbose=False):
        with self.workdir:
            cfy.blueprints.publish_archive(
                blueprint_id=blueprint_id,
                archive_location=archive_location,
                blueprint_filename='blueprint.yaml',
                verbose=verbose).wait()

    def create_deployment(self,
                          blueprint_id,
                          deployment_id,
                          verbose=False,
                          inputs=None):
        with self.workdir:
            inputs_file = self._get_inputs_in_temp_file(inputs, deployment_id)
            cfy.deployments.create(
                blueprint_id=blueprint_id,
                deployment_id=deployment_id,
                verbose=verbose,
                inputs=inputs_file).wait()

    def delete_deployment(self, deployment_id,
                          verbose=False,
                          ignore_live_nodes=False):
        with self.workdir:
            cfy.deployments.delete(
                deployment_id=deployment_id,
                ignore_live_nodes=ignore_live_nodes,
                verbose=verbose).wait()

    def delete_blueprint(self, blueprint_id,
                         verbose=False):
        with self.workdir:
            cfy.blueprints.delete(
                blueprint_id=blueprint_id,
                verbose=verbose).wait()

    def list_blueprints(self, verbose=False):
        with self.workdir:
            cfy.blueprints.list(verbose=verbose).wait()

    def list_deployments(self, verbose=False):
        with self.workdir:
            cfy.deployments.list(verbose=verbose).wait()

    def list_executions(self, verbose=False):
        with self.workdir:
            cfy.executions.list(verbose=verbose).wait()

    def list_events(self, execution_id, verbosity='', include_logs=True):
        with self.workdir:
            command = cfy_out.events.list.bake(
                execution_id=execution_id,
                include_logs=include_logs)
            if verbosity:
                command = command.bake(verbosity)
            return command().stdout.strip()

    def get_blueprint(self, blueprint_id, verbose=False):
        with self.workdir:
            cfy.blueprints.get(
                blueprint_id=blueprint_id, verbose=verbose).wait()

    def get_deployment(self, deployment_id, verbose=False):
        with self.workdir:
            cfy.deployments.get(
                deployment_id=deployment_id, verbose=verbose).wait()

    def get_execution(self, execution_id, verbose=False):
        with self.workdir:
            cfy.executions.get(
                execution_id=execution_id, verbose=verbose).wait()

    def cancel_execution(self, execution_id, verbose=False):
        with self.workdir:
            cfy.executions.cancel(
                execution_id=execution_id, verbose=verbose).wait()

    def execute_install(self,
                        deployment_id,
                        verbose=False,
                        include_logs=True,
                        execute_timeout=DEFAULT_EXECUTE_TIMEOUT):
        self.execute_workflow(
            workflow='install',
            deployment_id=deployment_id,
            execute_timeout=execute_timeout,
            verbose=verbose,
            include_logs=include_logs)

    def execute_uninstall(self,
                          deployment_id,
                          verbose=False,
                          include_logs=True,
                          execute_timeout=DEFAULT_EXECUTE_TIMEOUT):
        self.execute_workflow(
            workflow='uninstall',
            deployment_id=deployment_id,
            execute_timeout=execute_timeout,
            verbose=verbose,
            include_logs=include_logs)

    def upload_blueprint(self,
                         blueprint_id,
                         blueprint_path,
                         verbose=False):
        with self.workdir:
            cfy.blueprints.upload(
                blueprint_path=blueprint_path,
                blueprint_id=blueprint_id,
                verbose=verbose).wait()

    def download_plugin(self, plugin_id, output_file):
        with self.workdir:
            cfy.plugins.download(plugin_id=plugin_id, output=output_file)\
                .wait()

    def use(self, management_ip):
        with self.workdir:
            cfy.use(management_ip=management_ip).wait()


    def _set_management_creds(self, user, key, port):
        with self.workdir, update_wd_settings() as ws_settings:
            ws_settings.set_management_user(user)
            ws_settings.set_management_key(key)
            ws_settings.set_management_port(port)



    def install_agents(self, deployment_id=None, include_logs=False):
        with self.workdir:
            cfy.agents.install(deployment_id=deployment_id,
                               include_logs=include_logs).wait()

    def close(self):
        if self.tmpdir:
            shutil.rmtree(self._cfy_workdir)

    def execute_workflow(self,
                         workflow,
                         deployment_id,
                         verbose=False,
                         include_logs=True,
                         execute_timeout=DEFAULT_EXECUTE_TIMEOUT,
                         parameters=None):

        params_file = self._get_parameters_in_temp_file(parameters, workflow)
        with self.workdir:
            cfy.executions.start(
                workflow=workflow,
                deployment_id=deployment_id,
                timeout=execute_timeout,
                verbose=verbose,
                include_logs=include_logs,
                parameters=params_file).wait()

    def install_plugins_locally(self, blueprint_path):
        cfy.local(
            'install-plugins',
            blueprint_path=blueprint_path).wait()

    def _get_dict_in_temp_file(self, dictionary, prefix, suffix):
        dictionary = dictionary or {}
        file_ = tempfile.mktemp(prefix='{0}-'.format(prefix),
                                suffix=suffix,
                                dir=self.workdir)
        with open(file_, 'w') as f:
            f.write(json.dumps(dictionary))
        return file_

    def _get_inputs_in_temp_file(self, inputs, inputs_prefix):
        return self._get_dict_in_temp_file(dictionary=inputs,
                                           prefix=inputs_prefix,
                                           suffix='-inputs.json')

    def _get_parameters_in_temp_file(self, parameters, parameters_prefix):
        return self._get_dict_in_temp_file(dictionary=parameters,
                                           prefix=parameters_prefix,
                                           suffix='-parameters.json')

    def upgrade_manager(self,
                        blueprint_path,
                        inputs_file=None,
                        validate_only=False,
                        install_plugins=True):
        if not inputs_file:
            inputs_file = self._get_inputs_in_temp_file({}, 'manager')
        with self.workdir:
            cfy.upgrade(
                blueprint_path=blueprint_path,
                inputs=inputs_file,
                validate_only=validate_only,
                install_plugins=install_plugins).wait()

    def rollback_manager(self, blueprint_path, inputs_file=None):
        if not inputs_file:
            inputs_file = self._get_inputs_in_temp_file({}, 'manager')
        with self.workdir:
            cfy.rollback(
                blueprint_path=blueprint_path,
                inputs=inputs_file).wait()

    def set_maintenance_mode(self, activate):
        maintenance_handler = cfy.bake('maintenance-mode')
        with self.workdir:
            if activate:
                maintenance_handler.activate(wait=True).wait()
            else:
                maintenance_handler.deactivate().wait()

    @contextmanager
    def maintenance_mode(self):
        self.set_maintenance_mode(True)
        try:
            yield
        finally:
            self.set_maintenance_mode(False)
