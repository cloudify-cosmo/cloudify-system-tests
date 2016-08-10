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
import sh
import sys
import yaml
import logging
import tempfile
import requests
from contextlib import contextmanager

from cloudify_cli.config.config import CLOUDIFY_CONFIG_PATH
from cosmo_tester.framework.util import YamlPatcher, download_file

cfy_out = sh.cfy

DEFAULT_EXECUTE_TIMEOUT = 1800
INPUTS = 'inputs'
PARAMETERS = 'parameters'


def get_cfy():
    return sh.cfy.bake(
        _err_to_out=True,
        _out=lambda l: sys.stdout.write(l),
        _tee=True
    )


class CfyHelper(object):

    def __init__(self,
                 client,
                 workdir,
                 test_id,
                 manager_ip=None,
                 manager_user=None,
                 manager_key=None,
                 manager_port='22'):
        self.logger = logging.getLogger('TESTENV')
        self.logger.setLevel(logging.INFO)

        self._client = client
        self._test_id = test_id
        self._workdir = workdir

        self._cfy = get_cfy()
        if manager_ip is not None:
            self._cfy.use(
                manager_ip,
                manager_user=manager_user,
                manager_key=manager_key,
                manager_port=manager_port
            )

    @property
    def cfy(self):
        return self._cfy

    def bootstrap(self,
                  blueprint_path,
                  inputs=None,
                  install_plugins=True,
                  keep_up_on_failure=False,
                  validate_only=False,
                  task_retries=5,
                  task_retry_interval=90,
                  subgraph_retries=2,
                  verbose=False):

        with YamlPatcher(CLOUDIFY_CONFIG_PATH) as patch:
            prop_path = ('local_provider_context.'
                         'cloudify.workflows.subgraph_retries')
            patch.set_value(prop_path, subgraph_retries)

        inputs_file = self.get_inputs_in_temp_file(inputs, 'manager')

        self.cfy.bootstrap(
            blueprint_path,
            inputs=inputs_file,
            install_plugins=install_plugins,
            keep_up_on_failure=keep_up_on_failure,
            validate_only=validate_only,
            task_retries=task_retries,
            task_retry_interval=task_retry_interval,
            verbose=verbose,
        )

        if not validate_only:
            self._upload_plugins()

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

    def _upload_plugins(self):
        downloaded_wagon_paths = self._download_wagons()
        for wagon in downloaded_wagon_paths:
            self.logger.info('Uploading {0}'.format(wagon))
            self.cfy.plugins.upload(wagon, verbose=True)

    def list_events(self, execution_id, verbosity='', include_logs=True):
        command = cfy_out.events.list.bake(
            execution_id=execution_id,
            include_logs=include_logs)
        if verbosity:
            command = command.bake(verbosity)
        return command().stdout.strip()

    @contextmanager
    def maintenance_mode(self):
        self.cfy.maintenance_mode.activate(wait=True)
        try:
            yield
        finally:
            self.cfy.maintenance_mode.deactivate(wait=True)

    def _get_dict_in_temp_file(self, dictionary, prefix, suffix):
        dictionary = dictionary or {}
        file_ = tempfile.mktemp(prefix='{0}-'.format(prefix),
                                suffix=suffix,
                                dir=self._workdir)
        with open(file_, 'w') as f:
            f.write(yaml.dump(dictionary))
        return file_

    def get_inputs_in_temp_file(self, inputs, inputs_prefix):
        return self._get_dict_in_temp_file(dictionary=inputs,
                                           prefix=inputs_prefix,
                                           suffix='-inputs.json')

    def get_parameters_in_temp_file(self, parameters, parameters_prefix):
        return self._get_dict_in_temp_file(dictionary=parameters,
                                           prefix=parameters_prefix,
                                           suffix='-parameters.json')

    def create_deployment(
            self,
            blueprint_id,
            deployment_id,
            inputs=''):
        self.logger.info("attempting to create_deployment deployment {0}"
                         .format(deployment_id))

        inputs = self.get_inputs_in_temp_file(inputs, deployment_id)

        return self.cfy.deployments.create(
            blueprint_id=blueprint_id,
            deployment_id=deployment_id,
            inputs=inputs
        )
