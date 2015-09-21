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


import unittest
import logging
import sys
import shutil
import tempfile
import time
import copy
import os
import importlib
import json
from contextlib import contextmanager

import yaml
from path import path
import fabric.api
import fabric.context_managers

from cosmo_tester.framework.cfy_helper import (CfyHelper,
                                               DEFAULT_EXECUTE_TIMEOUT)
from cosmo_tester.framework.util import (get_blueprint_path,
                                         process_variables,
                                         YamlPatcher,
                                         generate_unique_configurations,
                                         create_rest_client)

from cloudify_rest_client.executions import Execution

root = logging.getLogger()
root.setLevel(logging.INFO)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
formatter = logging.Formatter(fmt='%(asctime)s [%(levelname)s] '
                                  '[%(name)s] %(message)s',
                              datefmt='%H:%M:%S')
ch.setFormatter(formatter)

# clear all other handlers
for logging_handler in root.handlers:
    root.removeHandler(logging_handler)

root.addHandler(ch)
logger = logging.getLogger('TESTENV')
logger.setLevel(logging.INFO)

HANDLER_CONFIGURATION = 'HANDLER_CONFIGURATION'
SUITES_YAML_PATH = 'SUITES_YAML_PATH'

test_environment = None


def initialize_without_bootstrap():
    logger.info('TestEnvironment initialize without bootstrap')
    global test_environment
    if not test_environment:
        test_environment = TestEnvironment()


def clear_environment():
    logger.info('TestEnvironment clear')
    global test_environment
    test_environment = None


def bootstrap(task_retries=5):
    logger.info('TestEnvironment initialize with bootstrap')
    global test_environment
    if not test_environment:
        test_environment = TestEnvironment()
        test_environment.bootstrap(task_retries)


def teardown():
    logger.info('TestEnvironment teardown')
    global test_environment
    if test_environment:
        try:
            logger.info('TestEnvironment teardown - starting')
            test_environment.teardown()
        finally:
            clear_environment()


# Singleton class
class TestEnvironment(object):
    # Singleton class
    def __init__(self):
        self._initial_cwd = os.getcwd()
        self._global_cleanup_context = None
        self._management_running = False
        self._additional_management_running = []
        self.rest_client = None
        self.additional_rest_clients = []
        self.management_ip = None
        self.additional_management_ips = []
        self.handler = None
        self._manager_blueprint_path = None
        self._workdir = tempfile.mkdtemp(prefix='cloudify-testenv-')
        self._additional_workdirs = []
        self._additional_managers = 0

        if HANDLER_CONFIGURATION not in os.environ:
            raise RuntimeError('handler configuration name must be configured '
                               'in "HANDLER_CONFIGURATION" env variable')
        handler_configuration = os.environ[HANDLER_CONFIGURATION]
        suites_yaml_path = os.environ.get(
            SUITES_YAML_PATH,
            path(__file__).dirname().dirname().dirname() / 'suites' /
            'suites' / 'suites.yaml')
        with open(suites_yaml_path) as f:
            self.suites_yaml = yaml.load(f.read())
        if os.path.exists(os.path.expanduser(handler_configuration)):
            configuration_path = os.path.expanduser(handler_configuration)
            with open(configuration_path) as f:
                self.handler_configuration = yaml.load(f.read())
        else:
            self.handler_configuration = self.suites_yaml[
                'handler_configurations'][handler_configuration]

        self.cloudify_config_path = path(os.path.expanduser(
            self.handler_configuration['inputs']))

        if not self.cloudify_config_path.isfile():
            raise RuntimeError('config file configured in handler '
                               'configuration does not seem to exist: {0}'
                               .format(self.cloudify_config_path))

        self.additional_cloudify_config_paths = [
            path(os.path.expanduser(p))
            for p in self.handler_configuration['additional_inputs']]

        for p in self.additional_cloudify_config_paths:
            if not p.isfile():
                raise RuntimeError('config file configured in handler '
                                   'configuration does not seem to exist: {0}'
                                   .format(p))

        if 'manager_blueprint' not in self.handler_configuration:
            raise RuntimeError(
                'manager blueprint must be configured in handler '
                'configuration')

        manager_blueprint = self.handler_configuration['manager_blueprint']
        self._manager_blueprint_path = os.path.expanduser(
            manager_blueprint)

        additional_managers_blueprints = self.handler_configuration.get(
            'additional_managers_blueprints', [])
        self._additional_managers_blueprints_paths = [
            os.path.expanduser(p) for p in additional_managers_blueprints]
        self._additional_managers = len(additional_managers_blueprints)

        blueprints_num = len(self._additional_managers_blueprints_paths)
        configs_num = len(self.additional_cloudify_config_paths)

        if blueprints_num != configs_num:
            raise RuntimeError('the number of configuration files is different '
                               '({0}) than the number of blueprints ({1}).'
                               .format(configs_num, blueprints_num))

        # make a temp config files than can be modified freely
        self._generate_unique_configurations()

        with YamlPatcher(self._manager_blueprint_path) as patch:
            manager_blueprint_override = process_variables(
                self.suites_yaml,
                self.handler_configuration.get(
                    'manager_blueprint_override', {}))
            for key, value in manager_blueprint_override.items():
                patch.set_value(key, value)

        handler = self.handler_configuration['handler']
        try:
            handler_module = importlib.import_module(
                'system_tests.{0}'.format(handler))
        except ImportError:
            handler_module = importlib.import_module(
                'suites.helpers.handlers.{0}.handler'.format(handler))
        handler_class = handler_module.handler
        self.handler = handler_class(self)

        self.cloudify_config = yaml.load(self.cloudify_config_path.text())
        self._config_reader = self.handler.CloudifyConfigReader(
            self.cloudify_config,
            manager_blueprint_path=self._manager_blueprint_path)
        with self.handler.update_cloudify_config() as patch:
            processed_inputs = process_variables(
                self.suites_yaml,
                self.handler_configuration.get('inputs_override', {}))
            for key, value in processed_inputs.items():
                patch.set_value(key, value)

        if 'manager_ip' in self.handler_configuration:
            self._running_env_setup(self.handler_configuration['manager_ip'])

        if 'additional_managers_ips' in self.handler_configuration:
            self._additional_running_env_setup(
                self.handler_configuration['additional_managers_ips'])

        self.install_plugins = self.handler_configuration.get(
            'install_manager_blueprint_dependencies', True)

        if self.handler_configuration.get('clean_env_on_init', False) is True:
            logger.info('Cleaning environment on init..')
            self.handler.CleanupContext.clean_all(self)

        self._additional_workdirs = [
            tempfile.mkdtemp(prefix='cloudify-testenv-')
            for _ in xrange(self._additional_managers)]

        global test_environment
        test_environment = self

    def _generate_unique_configurations(self):
        inputs_path, manager_blueprint_path = generate_unique_configurations(
            workdir=self._workdir,
            original_inputs_path=self.cloudify_config_path,
            original_manager_blueprint_path=self._manager_blueprint_path)
        self.cloudify_config_path = inputs_path
        self._manager_blueprint_path = manager_blueprint_path

    def setup(self):
        os.chdir(self._initial_cwd)
        return self

    def bootstrap(self, task_retries=5):
        if self._management_running:
            return

        self._global_cleanup_context = self.handler.CleanupContext(
            'testenv', self)

        cfy = CfyHelper(cfy_workdir=self._workdir)

        self.handler.before_bootstrap()
        cfy.bootstrap(
            self._manager_blueprint_path,
            inputs_file=self.cloudify_config_path,
            install_plugins=self.install_plugins,
            keep_up_on_failure=False,
            task_retries=task_retries,
            verbose=True)
        self._running_env_setup(cfy.get_management_ip())

        additional_managers_ips = []

        for i, blueprint_path in enumerate(
                self._additional_managers_blueprints_paths):
            cfy = CfyHelper(cfy_workdir=self._additional_workdirs[i])
            cfy.bootstrap(
                blueprint_path,
                inputs_file=self.additional_cloudify_config_paths[i],
                install_plugins=self.install_plugins,
                keep_up_on_failure=False,
                task_retries=task_retries,
                verbose=True)
            additional_managers_ips.append(cfy.get_management_ip())

        self._additional_running_env_setup(additional_managers_ips)

        self.handler.after_bootstrap(cfy.get_provider_context())

    def teardown(self):
        if self._global_cleanup_context is None:
            return
        self.setup()
        try:
            for workdir, ip in zip(self._additional_workdirs,
                                   self.additional_management_ips):
                cfy = CfyHelper(cfy_workdir=workdir)
                cfy.use(ip)
                cfy.teardown(verbose=True)

            cfy = CfyHelper(cfy_workdir=self._workdir)
            cfy.use(self.management_ip)
            cfy.teardown(verbose=True)

        finally:
            self._global_cleanup_context.cleanup()
            self.handler.after_teardown()
            if os.path.exists(self._workdir):
                shutil.rmtree(self._workdir)

            for workdir in self._additional_workdirs:
                if os.path.exists(workdir):
                    shutil.rmtree(workdir)

    def _running_env_setup(self, management_ip):
        self.management_ip = management_ip
        self.rest_client = create_rest_client(management_ip)
        response = self.rest_client.manager.get_status()
        if not response['status'] == 'running':
            raise RuntimeError('Manager at {0} is not running.'
                               .format(self.management_ip))
        self._management_running = True

    def _additional_running_env_setup(self, management_ips):
        self.additional_management_ips = management_ips

        for ip in self.additional_management_ips:
            self.additional_rest_clients.append(create_rest_client(ip))

            response = self.additional_rest_clients[-1].manager.get_status()
            if not response['status'] == 'running':
                raise RuntimeError('Additional manager at {0} is not running.'
                                   .format(ip))
            self._additional_management_running.append(True)

    def __getattr__(self, item):
        """Every attribute access on this env (usually from tests doing
        self.env, has the following semantics:
        First if env contains this attribute, use it, then
        if the handler has this attribute configured on it (this also includes
        handler_properties configured in the handler configuration), then
        use that, finally, check this attribute in the config reader.
        only then fail
        """

        if hasattr(self.handler, item):
            return getattr(self.handler, item)
        elif hasattr(self._config_reader, item):
            return getattr(self._config_reader, item)
        else:
            raise AttributeError(
                'Property \'{0}\' was not found in env'.format(item))


class TestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    def wait_until_deployment_ready_and_execute_install(self,
                                                        deployment_id,
                                                        inputs):
        self.wait_until_all_deployment_executions_end(deployment_id)
        return self.execute_install(deployment_id=deployment_id)

    def wait_until_all_deployment_executions_end(self, deployment_id):
        self.logger.info("waiting for executions on deployment {0} to finish"
                         .format(deployment_id))
        start_time = time.time()
        while len([execution for execution in self.client.executions.list(
                deployment_id=deployment_id)
                if execution["status"] not in Execution.END_STATES]) > 0:
            time.sleep(1)
            if start_time - time.time() > DEFAULT_EXECUTE_TIMEOUT:
                raise Exception("timeout while waiting for executions to end "
                                "on deployment {0}".format(deployment_id))
        return

    def assert_outputs(self, expected_outputs, deployment_id=None):
        if deployment_id is None:
            deployment_id = self.test_id
        outputs = self.client.deployments.outputs.get(deployment_id)
        outputs = outputs['outputs']
        self.assertEqual(expected_outputs, outputs)

    def setUp(self):
        global test_environment
        self.env = test_environment.setup()
        self.logger = logging.getLogger(self._testMethodName)
        self.logger.setLevel(logging.INFO)
        self.logger.info('Starting test setUp')
        self.workdir = tempfile.mkdtemp(prefix='cosmo-test-')
        self.additional_workdirs = [tempfile.mkdtemp(prefix='cosmo-test-')
                                    for _ in self.env.additional_management_ips]
        self.cfy = CfyHelper(cfy_workdir=self.workdir,
                             management_ip=self.env.management_ip,
                             testcase=self)
        self.additional_cfys = [
            CfyHelper(cfy_workdir=e[0], management_ip=e[1], testcase=self)
            for e in zip(self.additional_workdirs,
                         self.env.additional_management_ips)]
        self.client = self.env.rest_client
        self.additional_clients = self.env.additional_rest_clients
        self.test_id = 'system-test-{0}'.format(time.strftime("%Y%m%d-%H%M"))
        self.blueprint_yaml = None
        self._test_cleanup_context = self.env.handler.CleanupContext(
            self._testMethodName, self.env)
        # register cleanup
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self._test_cleanup_context.cleanup()
        shutil.rmtree(self.workdir)

    def tearDown(self):
        self.logger.info('Starting test tearDown')
        # note that the cleanup function is registered in setUp
        # because it is called regardless of whether setUp succeeded or failed
        # unlike tearDown which is not called when setUp fails (which might
        # happen when tests override setUp)

    def get_manager_state(self):
        self.logger.info('Fetching manager current state')
        blueprints = {}
        for blueprint in self.client.blueprints.list():
            blueprints[blueprint.id] = blueprint
        deployments = {}
        for deployment in self.client.deployments.list():
            deployments[deployment.id] = deployment
        nodes = {}
        for deployment_id in deployments.keys():
            for node in self.client.node_instances.list(deployment_id):
                nodes[node.id] = node
        deployment_nodes = {}
        node_state = {}
        for deployment_id in deployments.keys():
            deployment_nodes[deployment_id] = self.client.node_instances.list(
                deployment_id)
            node_state[deployment_id] = {}
            for node in deployment_nodes[deployment_id]:
                node_state[deployment_id][node.id] = node

        return {
            'blueprints': blueprints,
            'deployments': deployments,
            'nodes': nodes,
            'node_state': node_state,
            'deployment_nodes': deployment_nodes
        }

    def get_manager_state_delta(self, before, after):
        after = copy.deepcopy(after)
        for blueprint_id in before['blueprints'].keys():
            del after['blueprints'][blueprint_id]
        for deployment_id in before['deployments'].keys():
            del after['deployments'][deployment_id]
            del after['deployment_nodes'][deployment_id]
            del after['node_state'][deployment_id]
        for node_id in before['nodes'].keys():
            del after['nodes'][node_id]
        return after

    def execute_install(self,
                        deployment_id=None,
                        fetch_state=True):
        self.logger.info("attempting to execute install on deployment {0}"
                         .format(deployment_id))
        return self._make_operation_with_before_after_states(
            self.cfy.execute_install,
            fetch_state,
            deployment_id=deployment_id)

    def upload_deploy_and_execute_install(
            self,
            blueprint_id=None,
            deployment_id=None,
            fetch_state=True,
            execute_timeout=DEFAULT_EXECUTE_TIMEOUT,
            inputs=None):

        return self._make_operation_with_before_after_states(
            self.cfy.upload_deploy_and_execute_install,
            fetch_state,
            str(self.blueprint_yaml),
            blueprint_id=blueprint_id or self.test_id,
            deployment_id=deployment_id or self.test_id,
            execute_timeout=execute_timeout,
            inputs=inputs)

    def upload_blueprint(
            self,
            blueprint_id):
        self.logger.info("attempting to upload blueprint {0}"
                         .format(blueprint_id))
        return self.cfy.upload_blueprint(
            blueprint_id=blueprint_id,
            blueprint_path=str(self.blueprint_yaml))

    def create_deployment(
            self,
            blueprint_id,
            deployment_id,
            inputs):
        self.logger.info("attempting to create_deployment deployment {0}"
                         .format(deployment_id))
        return self.cfy.create_deployment(
            blueprint_id=blueprint_id,
            deployment_id=deployment_id,
            inputs=inputs)

    def _make_operation_with_before_after_states(self, operation, fetch_state,
                                                 *args, **kwargs):
        before_state = None
        after_state = None
        if fetch_state:
            before_state = self.get_manager_state()
        operation(*args, **kwargs)
        if fetch_state:
            after_state = self.get_manager_state()
        return before_state, after_state

    def execute_uninstall(self, deployment_id=None):
        self.cfy.execute_uninstall(deployment_id=deployment_id or self.test_id)

    def copy_blueprint(self, blueprint_dir_name, blueprints_dir=None):
        blueprint_path = path(self.workdir) / blueprint_dir_name
        shutil.copytree(get_blueprint_path(blueprint_dir_name, blueprints_dir),
                        str(blueprint_path))
        return blueprint_path

    def wait_for_execution(self, execution, timeout):
        end = time.time() + timeout
        while time.time() < end:
            status = self.client.executions.get(execution.id).status
            if status == 'failed':
                raise AssertionError('Execution "{}" failed'.format(
                    execution.id))
            if status == 'terminated':
                return
            time.sleep(1)
        events, _ = self.client.events.get(execution.id,
                                           batch_size=1000,
                                           include_logs=True)
        self.logger.info('Deployment creation events & logs:')
        for event in events:
            self.logger.info(json.dumps(event))
        raise AssertionError('Execution "{}" timed out'.format(execution.id))

    def wait_for_stop_dep_env_execution_to_end(self, deployment_id,
                                               timeout_seconds=240):
        executions = self.client.executions.list(
            deployment_id=deployment_id, include_system_workflows=True)
        running_stop_executions = [e for e in executions if e.workflow_id ==
                                   '_stop_deployment_environment' and
                                   e.status not in Execution.END_STATES]

        if not running_stop_executions:
            return

        if len(running_stop_executions) > 1:
            raise RuntimeError('There is more than one running '
                               '"_stop_deployment_environment" execution: {0}'
                               .format(running_stop_executions))

        execution = running_stop_executions[0]
        return self.wait_for_execution(execution, timeout_seconds)

    def repetitive(self, func, timeout=10, exception_class=Exception,
                   args=None, kwargs=None):
        args = args or []
        kwargs = kwargs or {}
        deadline = time.time() + timeout
        while True:
            try:
                return func(*args, **kwargs)
            except exception_class:
                if time.time() > deadline:
                    raise
                time.sleep(1)

    @contextmanager
    def manager_env_fabric(self, **kwargs):
        with fabric.context_managers.settings(
                host_string=self.cfy.get_management_ip(),
                user=self.env.management_user_name,
                key_filename=self.env.management_key_path,
                **kwargs):
            yield fabric.api
