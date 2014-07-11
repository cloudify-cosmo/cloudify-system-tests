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

__author__ = 'Oleksandr_Raskosov'


import unittest
import logging
import tempfile
import time
import shutil
import os
from path import path
import yaml
from cosmo_tester.framework.ec2_cfy_helper import EC2CfyHelper
from cosmo_tester.framework.ec2_util import EC2CloudifyConfigReader
from cloudify_rest_client import CloudifyClient
from cosmo_tester.framework.ec2_api import (ec2_infra_state,
                                            ec2_infra_state_delta,
                                            remove_ec2_resources)

CLOUDIFY_TEST_CONFIG_PATH = 'CLOUDIFY_TEST_CONFIG_PATH'
CLOUDIFY_TEST_MANAGEMENT_IP = 'CLOUDIFY_TEST_MANAGEMENT_IP'
CLOUDIFY_TEST_NO_CLEANUP = 'CLOUDIFY_TEST_NO_CLEANUP'

EC2_IMAGE_NAME = 'ami-fb8e9292'
EC2_IMAGE_SIZE = 't1.micro'


test_environment = None


class TestCase(unittest.TestCase):

    def setUp(self):
        self.env = test_environment.setup()
        self.logger = logging.getLogger(self._testMethodName)
        self.logger.setLevel(logging.INFO)
        self.workdir = tempfile.mkdtemp(prefix='cosmo-test-')
        self.cfy = EC2CfyHelper(cfy_workdir=self.workdir,
                                management_ip=self.env.management_ip)
        self.client = self.env.rest_client
        self.test_id = 'system-test-{0}'.format(time.strftime("%Y%m%d-%H%M"))
        self.blueprint_yaml = None
        self._test_cleanup_context = CleanupContext(self._testMethodName,
                                                    self.env.cloudify_config)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self._test_cleanup_context.cleanup()
        shutil.rmtree(self.workdir)

    def tearDown(self):
        # note that the cleanup function is registered in setUp
        # because it is called regardless of whether setUp succeeded or failed
        # unlike tearDown which is not called when setUp fails (which might
        # happen when tests override setUp)
        pass


class CleanupContext(object):

    logger = logging.getLogger('CleanupContext')
    logger.setLevel(logging.DEBUG)

    def __init__(self, context_name, cloudify_config):
        self.context_name = context_name
        self.cloudify_config = cloudify_config
        self.before_run = ec2_infra_state(cloudify_config)

    def cleanup(self):
        resources_to_teardown = self.get_resources_to_teardown()
        if os.environ.get(CLOUDIFY_TEST_NO_CLEANUP):
            self.logger.warn('[{0}] SKIPPING cleanup: of the resources: {1}'
                             .format(self.context_name, resources_to_teardown))
            return
        self.logger.info('[{0}] Performing cleanup: will try removing these '
                         'resources: {1}'
                         .format(self.context_name, resources_to_teardown))

        remove_ec2_resources(self.cloudify_config,
                             resources_to_teardown)

    def get_resources_to_teardown(self):
        current_state = ec2_infra_state(self.cloudify_config)
        return ec2_infra_state_delta(before=self.before_run,
                                     after=current_state)


# Singleton class
class TestEnvironment(object):

    # Singleton class
    def __init__(self):
        self._initial_cwd = os.getcwd()
        self._global_cleanup_context = None
        self._management_running = False
        self.rest_client = None
        self.management_ip = None

        if CLOUDIFY_TEST_CONFIG_PATH not in os.environ:
            raise RuntimeError('a path to cloudify-config must be configured '
                               'in "CLOUDIFY_TEST_CONFIG_PATH" env variable')
        self.cloudify_config_path = path(os.environ[CLOUDIFY_TEST_CONFIG_PATH])

        if not self.cloudify_config_path.isfile():
            raise RuntimeError('cloud-config file configured in env variable'
                               ' {0} does not seem to exist'
                               .format(self.cloudify_config_path))
        self.cloudify_config = yaml.load(self.cloudify_config_path.text())

        if CLOUDIFY_TEST_MANAGEMENT_IP in os.environ:
            self._running_env_setup(os.environ[CLOUDIFY_TEST_MANAGEMENT_IP])

        self._config_reader = EC2CloudifyConfigReader(self.cloudify_config)

        global test_environment
        test_environment = self

    def setup(self):
        os.chdir(self._initial_cwd)
        return self

    def bootstrap(self):
        if self._management_running:
            return
        self._global_cleanup_context = CleanupContext('testenv',
                                                      self.cloudify_config)
        cfy = EC2CfyHelper()
        try:
            cfy.bootstrap(
                self.cloudify_config_path,
                keep_up_on_failure=False,
                verbose=True,
                dev_mode=False)
            self._running_env_setup(cfy.get_management_ip())
        finally:
            cfy.close()

    def teardown(self):
        if self._global_cleanup_context is None:
            return
        self.setup()
        cfy = EC2CfyHelper()
        try:
            cfy.use(self.management_ip)
            cfy.teardown(
                self.cloudify_config_path,
                verbose=True)
        finally:
            cfy.close()
            self._global_cleanup_context.cleanup()

    def _running_env_setup(self, management_ip):
        self.management_ip = management_ip
        self.rest_client = CloudifyClient(self.management_ip)
        response = self.rest_client.manager.get_status()
        if not response['status'] == 'running':
            raise RuntimeError('Manager at {0} is not running.'
                               .format(self.management_ip))
        self._management_running = True

    # @property
    # def management_network_name(self):
    #     return self._config_reader.management_network_name
    #
    # @property
    # def agent_key_path(self):
    #     return self._config_reader.agent_key_path
    #
    # @property
    # def agent_keypair_name(self):
    #     return self._config_reader.agent_keypair_name
    #
    # @property
    # def external_network_name(self):
    #     return self._config_reader.external_network_name
    #
    # @property
    # def agents_security_group(self):
    #     return self._config_reader.agents_security_group
    #
    # @property
    # def management_server_name(self):
    #     return self._config_reader.management_server_name
    #
    # @property
    # def management_server_floating_ip(self):
    #     return self._config_reader.management_server_floating_ip
    #
    # @property
    # def management_sub_network_name(self):
    #     return self._config_reader.management_sub_network_name
    #
    # @property
    # def management_router_name(self):
    #     return self._config_reader.management_router_name
    #
    @property
    def managment_user_name(self):
        return self._config_reader.managment_user_name

    @property
    def management_key_path(self):
        return self._config_reader.management_key_path

    # @property
    # def management_keypair_name(self):
    #     return self._config_reader.management_keypair_name
    #
    # @property
    # def management_security_group(self):
    #     return self._config_reader.management_security_group
    #
    # @property
    # def ubuntu_image_name(self):
    #     return EC2_IMAGE_NAME
    #
    # @property
    # def flavor_name(self):
    #     return EC2_IMAGE_SIZE


def clear_environment():
    global test_environment
    test_environment = None


def bootstrap():
    global test_environment
    if not test_environment:
        test_environment = TestEnvironment()
    test_environment.bootstrap()


def teardown():
    global test_environment
    if test_environment:
        test_environment.teardown()
        clear_environment()
