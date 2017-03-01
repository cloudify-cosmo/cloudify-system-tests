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

from abc import ABCMeta, abstractmethod

import json
import os
import shutil
import uuid

from fabric import api as fabric_api
from fabric import context_managers as fabric_context_managers
import sh

from cosmo_tester.framework import util
from cosmo_tester.framework import git_helper

REMOTE_PRIVATE_KEY_PATH = '/etc/cloudify/key.pem'
REMOTE_OPENSTACK_CONFIG_PATH = '/root/openstack_config.json'

MANAGER_BLUEPRINTS_REPO_URL = 'https://github.com/cloudify-cosmo/cloudify-manager-blueprints.git'  # noqa


class CloudifyManager(object):

    __metaclass__ = ABCMeta

    def __init__(self, cfy, ssh_key, tmpdir, attributes, logger):
        super(CloudifyManager, self).__init__()
        self.logger = logger
        self.attributes = attributes
        self.tmpdir = tmpdir
        self.ssh_key = ssh_key
        self.cfy = cfy
        self._ip_address = None
        self._private_ip_address = None
        self._client = None
        self._terraform = util.sh_bake(sh.terraform)
        self._terraform_inputs_file = self.tmpdir / 'terraform-vars.json'

    def _create_manager(self):
        pass

    @abstractmethod
    def _get_manager_image_name(self):
        """Returns the image name for the manager's VM."""
        pass

    @staticmethod
    def create_image_based(cfy, ssh_key, tmpdir, attributes, logger):
        """Creates an image based Cloudify manager."""
        manager = ImageBasedCloudifyManager(cfy, ssh_key, tmpdir, attributes,
                                            logger)
        logger.info('Creating cloudify manager from image..')
        manager.create()
        return manager

    @staticmethod
    def create_bootstrap_based(cfy, ssh_key, tmpdir, attributes, logger):
        """Bootstraps a Cloudify manager using simple manager blueprint."""
        manager = BootstrapBasedCloudifyManager(cfy,
                                                ssh_key,
                                                tmpdir,
                                                attributes,
                                                logger)
        logger.info('Bootstrapping cloudify manager using simple '
                    'manager blueprint..')
        manager.create()
        return manager

    @property
    def ip_address(self):
        """Returns the manager's public IP address."""
        if not self._ip_address:
            raise RuntimeError('ip_address was not set!')
        return self._ip_address

    @property
    def private_ip_address(self):
        """Returns the manager's private IP address."""
        if not self._private_ip_address:
            raise RuntimeError('private_ip_address was not set!')
        return self._private_ip_address

    @property
    def client(self):
        """Returns a REST client initialized to work with the manager."""
        if not self._client:
            raise RuntimeError('client was not set!')
        return self._client

    @property
    def remote_private_key_path(self):
        """Returns the private key path on the manager."""
        return REMOTE_PRIVATE_KEY_PATH

    def create(self):
        """Creates the OpenStack infrastructure for a Cloudify manager.

        The openstack credentials file and private key file for SSHing
        to provisioned VMs are uploaded to the server."""
        openstack_config_file = self.tmpdir / 'openstack_config.json'
        openstack_config_file.write_text(json.dumps({
            'username': os.environ['OS_USERNAME'],
            'password': os.environ['OS_PASSWORD'],
            'tenant_name': os.environ.get('OS_TENANT_NAME',
                                          os.environ['OS_PROJECT_NAME']),
            'auth_url': os.environ['OS_AUTH_URL']
        }, indent=2))

        terraform_template_file = self.tmpdir / 'openstack-vm.tf'

        shutil.copy(util.get_resource_path('terraform/openstack-vm.tf'),
                    terraform_template_file)

        image_name = self._get_manager_image_name()
        self.logger.info('Cloudify manager image name: %s', image_name)

        self._terraform_inputs_file.write_text(json.dumps({
            'resource_suffix': str(uuid.uuid4()),
            'public_key_path': self.ssh_key.public_key_path,
            'private_key_path': self.ssh_key.private_key_path,
            'flavor': self.attributes.large_flavor_name,
            'image': image_name,
        }, indent=2))

        try:
            with self.tmpdir:
                self._terraform.apply(['-var-file',
                                       self._terraform_inputs_file])
                outputs = util.AttributesDict(
                        {k: v['value'] for k, v in json.loads(
                                self._terraform.output(['-json']).stdout).items()})
            self.attributes.update(outputs)
            self._ip_address = outputs.public_ip_address
            self._private_ip_address = outputs.private_ip_address

            self._create_manager()

            self._client = util.create_rest_client(
                    self.ip_address,
                    username=self.attributes.cloudify_username,
                    password=self.attributes.cloudify_password,
                    tenant=self.attributes.cloudify_tenant)

            self.cfy.profiles.use('{0} -u {1} -p {2} -t {3}'.format(
                    self.ip_address,
                    self.attributes.cloudify_username,
                    self.attributes.cloudify_password,
                    self.attributes.cloudify_tenant).split())

            self._upload_necessary_files_to_manager(openstack_config_file)
            self._upload_openstack_plugin_to_manager()

            self.logger.info('Cloudify manager successfully created!')

        except Exception as e:
            self.logger.error(
                    'Error creating cloudify manager from image: %s', e)
            try:
                self.destroy()
            except sh.ErrorReturnCode as ex:
                self.logger.error('Error on terraform destroy: %s', ex)
            raise

    def _upload_openstack_plugin_to_manager(self):
        plugins_list = util.get_plugin_wagon_urls()
        openstack_plugin_wagon = [
            x['wgn_url'] for x in plugins_list
            if x['name'] == 'openstack_centos_core']
        if len(openstack_plugin_wagon) != 1:
            self.logger.error(
                    'OpenStack plugin wagon not found in:%s%s',
                    os.linesep, json.dumps(plugins_list, indent=2))
            raise RuntimeError('OpenStack plugin not found in wagons list')
        self.logger.info('Uploading openstack plugin to manager.. [%s]',
                    openstack_plugin_wagon[0])
        self.client.plugins.upload(openstack_plugin_wagon[0])
        self.cfy.plugins.list()

    def _upload_necessary_files_to_manager(self, openstack_config_file):
        self.logger.info('Uploading necessary files to manager..')
        with fabric_context_managers.settings(
                host_string=self.ip_address,
                user=self.attributes.centos7_username,
                key_filename=self.ssh_key.private_key_path,
                connections_attempts=3,
                abort_on_prompts=True):
            fabric_api.put(openstack_config_file,
                           REMOTE_OPENSTACK_CONFIG_PATH,
                           use_sudo=True)
            fabric_api.put(self.ssh_key.private_key_path,
                           REMOTE_PRIVATE_KEY_PATH,
                           use_sudo=True)
            fabric_api.sudo('chmod 400 {}'.format(REMOTE_PRIVATE_KEY_PATH))

    def destroy(self):
        """Destroys the OpenStack infrastructure."""
        self.logger.info('Destroying cloudify manager..')
        with self.tmpdir:
            self._terraform.destroy(
                    ['-var-file', self._terraform_inputs_file, '-force'])


class ImageBasedCloudifyManager(CloudifyManager):
    """
    Starts a manager from an image on OpenStack.
    """

    def _get_manager_image_name(self):
        """
        Returns the manager image name based on installed CLI version.
        For CLI version "4.0.0-m15"
        Returns: "cloudify-manager-premium-4.0m15"
        """
        version = util.get_cli_version().replace('-', '').replace('0.0', '0')
        return '{}-{}'.format(
                self.attributes.cloudify_manager_image_name_prefix, version)


class BootstrapBasedCloudifyManager(CloudifyManager):
    """
    Bootstraps a Cloudify manager using simple manager blueprint.
    """

    def __init__(self, *args, **kwargs):
        super(BootstrapBasedCloudifyManager, self).__init__(*args, **kwargs)
        self._manager_resources_package = \
            util.get_manager_resources_package_url()
        self._manager_blueprints_path = None
        self._inputs_file = None

    def _get_manager_image_name(self):
        return self.attributes.centos7_image_name

    def _create_manager(self):
        super(BootstrapBasedCloudifyManager, self)._create_manager()

        self._clone_manager_blueprints()
        self._create_inputs_file()
        self._bootstrap_manager()

    def _clone_manager_blueprints(self):
        self._manager_blueprints_path = git_helper.clone(
                MANAGER_BLUEPRINTS_REPO_URL,
                str(self.tmpdir))

    def _create_inputs_file(self):
        self._inputs_file = self.tmpdir / 'inputs.json'
        bootstrap_inputs = json.dumps({
            'public_ip': self.ip_address,
            'private_ip': self.private_ip_address,
            'ssh_user': self.attributes.centos7_username,
            'ssh_key_filename': self.ssh_key.private_key_path,
            'admin_username': self.attributes.cloudify_username,
            'admin_password': self.attributes.cloudify_password,
            'manager_resources_package': self._manager_resources_package},
            indent=2)
        self.logger.info('Bootstrap inputs:%s%s', os.linesep, bootstrap_inputs)
        self._inputs_file.write_text(bootstrap_inputs)

    def _bootstrap_manager(self):
        manager_blueprint_path = \
            self._manager_blueprints_path / 'simple-manager-blueprint.yaml'
        self.cfy.bootstrap([manager_blueprint_path, '-i', self._inputs_file])
