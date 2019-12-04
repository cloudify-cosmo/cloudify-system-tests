########
# Copyright (c) 2018 Cloudify Platform Ltd. All rights reserved
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
from contextlib import contextmanager

from cloudify_cli.constants import DEFAULT_TENANT_NAME

from fabric import api as fabric_api
from fabric import context_managers as fabric_context_managers

from cosmo_tester.framework import util
from cosmo_tester.framework.examples import AbstractExample
from . import constants


class AbstractRegionalCluster(AbstractExample):
    REPOSITORY_URL = 'https://{0}@github.com/' \
                     'cloudify-cosmo/cloudify-spire-plugin.git'.format(
                         os.environ['GITHUB_TOKEN'])
    TRANSFER_AGENTS = None

    def __init__(self, *args, **kwargs):
        super(AbstractRegionalCluster, self).__init__(*args, **kwargs)
        self._deployed = False

    @property
    def deployed(self):
        return self._deployed

    @deployed.setter
    def deployed(self, value):
        self._deployed = value

    @property
    def _base_inputs(self):

        openstack_config = util.get_openstack_config()

        inputs = {
            'endpoint_ip_property': 'private_ip',
            'database-infrastructure--'
            'os_password': openstack_config['password'],
            'database-infrastructure--'
            'os_username': openstack_config['username'],
            'database-infrastructure--'
            'os_tenant': openstack_config['tenant_name'],
            'database-infrastructure--'
            'os_auth_url': openstack_config['auth_url'],
            'database-infrastructure--'
            'os_region': os.environ['OS_REGION_NAME'],

            'database-infrastructure--'
            'agent_installation_method': 'remote',
            'database-infrastructure--'
            'use_existing_openstack_resources': True,
            'database-infrastructure--'
            'use_public_ip': False,
            'database-infrastructure--'
            'manager_agent_broker': 'default',

            'database-infrastructure--'
            'os_image': self.attributes.centos_7_image_id,
            'database-infrastructure--'
            'os_flavor': '3',
            'database-infrastructure--'
            'os_volume_size': 20,
            'database-infrastructure--'
            'os_device_mapping': [],
            'database-infrastructure--'
            'os_network': self.attributes.network_name,
            'database-infrastructure--'
            'os_subnet': self.attributes.subnet_name,
            'database-infrastructure--'
            'os_keypair': self.attributes.keypair_name,
            'database-infrastructure--'
            'os_security_group': self.attributes.security_group_name,

            'database-infrastructure--'
            'ssh_user': self.attributes.default_linux_username,
            'database-infrastructure--'
            'ssh_private_key_path': self.manager.remote_private_key_path,

            'queue-infrastructure--'
            'os_password': openstack_config['password'],
            'queue-infrastructure--'
            'os_username': openstack_config['username'],
            'queue-infrastructure--'
            'os_tenant': openstack_config['tenant_name'],
            'queue-infrastructure--'
            'os_auth_url': openstack_config['auth_url'],
            'queue-infrastructure--'
            'os_region': os.environ['OS_REGION_NAME'],

            'queue-infrastructure--'
            'agent_installation_method': 'remote',
            'queue-infrastructure--'
            'use_existing_openstack_resources': True,
            'queue-infrastructure--'
            'use_public_ip': False,
            'queue-infrastructure--'
            'manager_agent_broker': 'default',

            'queue-infrastructure--'
            'os_image': self.attributes.centos_7_image_id,
            'queue-infrastructure--'
            'os_flavor': '3',
            'queue-infrastructure--'
            'os_volume_size': 20,
            'queue-infrastructure--'
            'os_device_mapping': [],
            'queue-infrastructure--'
            'os_network': self.attributes.network_name,
            'queue-infrastructure--'
            'os_subnet': self.attributes.subnet_name,
            'queue-infrastructure--'
            'os_keypair': self.attributes.keypair_name,
            'queue-infrastructure--'
            'os_security_group': self.attributes.security_group_name,

            'queue-infrastructure--'
            'ssh_user': self.attributes.default_linux_username,
            'queue-infrastructure--'
            'ssh_private_key_path': self.manager.remote_private_key_path,

            'worker-infrastructure--'
            'os_password': openstack_config['password'],
            'worker-infrastructure--'
            'os_username': openstack_config['username'],
            'worker-infrastructure--'
            'os_tenant': openstack_config['tenant_name'],
            'worker-infrastructure--'
            'os_auth_url': openstack_config['auth_url'],
            'worker-infrastructure--'
            'os_region': os.environ['OS_REGION_NAME'],

            'worker-infrastructure--'
            'agent_installation_method': 'remote',
            'worker-infrastructure--'
            'use_existing_openstack_resources': True,
            'worker-infrastructure--'
            'use_public_ip': False,
            'worker-infrastructure--'
            'manager_agent_broker': 'default',

            'worker-infrastructure--'
            'os_image': self.attributes.centos_7_image_id,
            'worker-infrastructure--'
            'os_flavor': '3',
            'worker-infrastructure--'
            'os_volume_size': 20,
            'worker-infrastructure--'
            'os_device_mapping': [],
            'worker-infrastructure--'
            'os_network': self.attributes.network_name,
            'worker-infrastructure--'
            'os_subnet': self.attributes.subnet_name,
            'worker-infrastructure--'
            'os_keypair': self.attributes.keypair_name,
            'worker-infrastructure--'
            'os_security_group': self.attributes.security_group_name,

            'worker-infrastructure--'
            'ssh_user': self.attributes.default_linux_username,
            'worker-infrastructure--'
            'ssh_private_key_path': self.manager.remote_private_key_path,

            'haproxy-infrastructure--'
            'os_password': openstack_config['password'],
            'haproxy-infrastructure--'
            'os_username': openstack_config['username'],
            'haproxy-infrastructure--'
            'os_tenant': openstack_config['tenant_name'],
            'haproxy-infrastructure--'
            'os_auth_url': openstack_config['auth_url'],
            'haproxy-infrastructure--'
            'os_region': os.environ['OS_REGION_NAME'],

            'haproxy-infrastructure--'
            'agent_installation_method': 'remote',
            'haproxy-infrastructure--'
            'use_existing_openstack_resources': True,
            'haproxy-infrastructure--'
            'use_public_ip': False,
            'haproxy-infrastructure--'
            'manager_agent_broker': 'default',

            'haproxy-infrastructure--'
            'os_image': self.attributes.centos_7_image_id,
            'haproxy-infrastructure--'
            'os_flavor': '2',
            'haproxy-infrastructure--'
            'os_volume_size': 20,
            'haproxy-infrastructure--'
            'os_device_mapping': [],
            'haproxy-infrastructure--'
            'os_network': self.attributes.network_name,
            'haproxy-infrastructure--'
            'os_subnet': self.attributes.subnet_name,
            'haproxy-infrastructure--'
            'os_keypair': self.attributes.keypair_name,
            'haproxy-infrastructure--'
            'os_security_group': self.attributes.security_group_name,

            'haproxy-infrastructure--'
            'ssh_user': self.attributes.default_linux_username,
            'haproxy-infrastructure--'
            'ssh_private_key_path': self.manager.remote_private_key_path,

            'ca_cert': self.attributes.LOCAL_REST_CERT_FILE,
            'ca_key': self.attributes.LOCAL_REST_KEY_FILE,
            'install_rpm_path': constants.INSTALL_RPM_PATH,
            'manager_admin_password': self.attributes.cloudify_password,

            'num_of_worker_instances': 2,

            # We're uploading the private SSH key and OS config from
            # the Central manager to the Regional managers, to be used later
            # in the bash script (see SCRIPT_SH in constants)

            'files': [
                {
                    'src': self.manager.remote_private_key_path,
                    'dst': constants.SSH_KEY_TMP_PATH
                },
                {
                    'src': self.manager.remote_public_key_path,
                    'dst': constants.PUB_KEY_TMP_PATH
                },
                {
                    'src': constants.REMOTE_OPENSTACK_CONFIG_PATH,
                    'dst': constants.OS_CONFIG_TMP_PATH
                },
                {
                    'src': constants.SCRIPT_SH_PATH,
                    'dst': constants.SCRIPT_SH_PATH,
                    'exec': True
                },
                {
                    'src': constants.SCRIPT_PY_PATH,
                    'dst': constants.SCRIPT_PY_PATH,
                    'exec': True
                },
            ],

            # Config in the same format as config.yaml
            # Skipping sanity to save time
            'additional_config': {'sanity': {'skip_sanity': True}}
        }

        return inputs

    @property
    def inputs(self):
        # To see explanations of the following inputs, see
        # https://github.com/cloudify-cosmo/cloudify-spire-plugin/
        # tree/master/blueprints/include
        inputs = self._base_inputs

        inputs.update({
            'endpoint_ip_property': 'public_ip_address',
            'database-infrastructure--'
            'os_floating_network': 'GATEWAY_NET',
            'queue-infrastructure--'
            'os_floating_network': 'GATEWAY_NET',
            'worker-infrastructure--'
            'os_floating_network': 'GATEWAY_NET',
            'haproxy-infrastructure--'
            'os_network': self.attributes.network_name,

        })

        inputs.update(self.network_inputs)

        if self.first_deployment:
            additional_inputs = self._get_additional_resources_inputs()
        else:
            additional_inputs = self._get_upgrade_inputs()

        inputs.update(additional_inputs)

        return inputs

    def _get_upgrade_inputs(self):
        # A trick to get the deployment ID of the first cluster
        old_deployment_id = self.deployment_id.replace(
            constants.SECOND_DEP_INDICATOR,
            constants.FIRST_DEP_INDICATOR
        )
        return {
                'restore': True,
                'restore_params': {
                    'force': True,
                    'recreate_deployments_envs': True,
                    'restore_certificates': True,
                    'no_reboot': True,
                    'ignore_plugin_failure': True
                },
                'old_deployment_id': old_deployment_id,
                'snapshot_id': old_deployment_id,
                'transfer_agents': self.TRANSFER_AGENTS
            }

    def _get_additional_resources_inputs(self):
        return {

                'tenants': [constants.TENANT_1, constants.TENANT_2],

                'plugins': [
                    {
                        'wagon': constants.OS_PLUGIN_WGN_URL,
                        'yaml': constants.OS_PLUGIN_YAML_URL,
                        'tenant': constants.TENANT_1
                    },
                    {
                        'wagon': constants.UTIL_PLUGIN_WGN_URL,
                        'yaml': constants.UTIL_PLUGIN_YAML_URL,
                        'visibility': 'global'
                    },
                    {
                        'wagon': constants.ANSIBLE_PLUGIN_WGN_URL,
                        'yaml': constants.ANSIBLE_PLUGIN_YAML_URL,
                        'visibility': 'global'
                    }
                ],

                'secrets': [

                    {
                        'key': constants.SECRET_STRING_KEY,
                        'string': constants.SECRET_STRING_VALUE,
                        'tenant': constants.TENANT_2
                    },

                    {
                        'key': constants.SECRET_FILE_KEY,
                        'file': constants.SCRIPT_SH_PATH,
                        'visibility': 'global'
                    },
                    {
                        'key': 'openstack_auth_url',
                        'string': os.environ.get('OS_AUTH_URL'),
                        'visibility': 'global'
                    },
                    {
                        'key': 'openstack_username',
                        'string': os.environ.get('OS_USERNAME'),
                        'visibility': 'global'
                    },
                    {
                        'key': 'openstack_password',
                        'string': os.environ.get('OS_PASSWORD'),
                        'visibility': 'global'
                    },
                    {
                        'key': 'openstack_tenant_name',
                        'string': os.environ.get(
                            util.OS_TENANT_NAME_ENV,
                            os.environ[util.OS_PROJECT_NAME_ENV]),
                        'visibility': 'global'
                    },
                    {
                        'key': 'agent_key_private',
                        'file': constants.SSH_KEY_TMP_PATH,
                        'visibility': 'global'
                    },
                    {
                        'key': 'agent_key_public',
                        'file': constants.PUB_KEY_TMP_PATH,
                        'visibility': 'global'
                    },
                ],

                'blueprints': [
                    {
                        'path': constants.HELLO_WORLD_URL,
                        'filename': 'openstack.yaml',
                        'id': constants.HELLO_WORLD_BP,
                        'tenant': constants.TENANT_1
                    },
                ],

                'deployments': [
                    {
                        'deployment_id': constants.HELLO_WORLD_DEP,
                        'blueprint_id': constants.HELLO_WORLD_BP,
                        'tenant': constants.TENANT_1,
                        'inputs': {
                            'region': 'RegionOne',
                            'external_network_id':
                                self.attributes.floating_network_id,
                            'image': self.attributes.ubuntu_14_04_image_id,
                            'flavor': self.attributes.medium_flavor_name
                        }
                    }
                ]
            }

    @property
    def network_inputs(self):
        raise NotImplementedError('Each Regional Cluster class needs to '
                                  'add additional network inputs')

    def validate(self):
        raise NotImplementedError('Each Regional Cluster class needs to '
                                  'implement the `validate` method')

    @property
    def first_deployment(self):
        """
        Indicate that this is the initial deployment, as opposed to the second
        one, to which we will upgrade
        """
        return constants.FIRST_DEP_INDICATOR in self.deployment_id

    @property
    def cluster_endpoint(self):
        return self.outputs['endpoint']

    def upload_blueprint(self, use_cfy=False):
        self.clone_example()
        namespace_blueprint_file = self._cloned_to / \
            'blueprints/infrastructure-examples/openstack/' \
            'floating-ip-configuration.yaml'
        namespace_blueprint_id = 'infra'
        blueprint_file = self._cloned_to / self.blueprint_file

        self.logger.info('Uploading blueprint: %s [id=%s]',
                         namespace_blueprint_file,
                         namespace_blueprint_id)
        self.logger.info('Uploading blueprint: %s [id=%s]',
                         blueprint_file,
                         self.blueprint_id)

        if use_cfy:
            self.cfy.profile.set([
                '-t', self.tenant,
            ])
            self.cfy.blueprint.upload([
                '-b', namespace_blueprint_id,
                namespace_blueprint_file
            ])
            self.cfy.blueprint.upload([
                '-b', self.blueprint_id,
                blueprint_file
            ])
        else:
            if self.first_deployment:
                with util.set_client_tenant(self.manager, self.tenant):
                    self.manager.client.blueprints.upload(
                        namespace_blueprint_file, namespace_blueprint_id)
                    self.manager.client.blueprints.upload(
                        blueprint_file, self.blueprint_id)

    def install(self, timeout=3600):
        super(AbstractRegionalCluster, self).install(timeout)
        self._populate_status_output()

    def clean_blueprints(self):
        if self.first_deployment:
            self.delete_blueprint()
            self.manager.client.blueprints.delete('infra', force=True)

    def _populate_status_output(self):
        # This workflow populates the deployment outputs with status info
        self.cfy.executions.start('get_status', '-d', self.deployment_id)
        self.cfy.deployments.capabilities(self.deployment_id)

    def verify_installation(self):
        super(AbstractRegionalCluster, self).verify_installation()
        assert self.cluster_endpoint

    def deploy_and_validate(self, timeout=3600):
        if self._deployed:
            self.logger.info('Regional cluster was already deployed')
            return
        self.logger.info(
            'Deploying Regional cluster on deployment: {0}'.format(
                self.deployment_id
            )
        )
        self._deployed = True
        self.upload_and_verify_install(timeout)
        self.validate()

    def backup(self):
        self.logger.info(
            'Running backup workflow on Regional '
            'cluster on dep: {0}...'.format(
                self.deployment_id
            )
        )

        backup_params = {
            'snapshot_id': self.deployment_id,
            'backup_params': []
        }
        self.cfy.executions.start(
            'backup', '-d', self.deployment_id,
            '-p', json.dumps(backup_params)
        )
        self.logger.info('Backup completed successfully')

    def scale(self):
        self.logger.info('Scaling deployment...')
        self._cleanup_required = True
        try:
            self.cfy.executions.start.scale(
                ['-d', self.deployment_id,
                 '-p', 'scalable_entity_name=workers_group',
                 '-p', 'delta=1',
                 '-t', self.tenant,
                 '--timeout', '3600'])
        except Exception as e:
            if 'if there is a running system-wide' in e.message:
                self.logger.error('Error on deployment execution: %s', e)
                self.logger.info('Listing executions..')
                self.cfy.executions.list(['-d', self.deployment_id])
                self.cfy.executions.list(['--include-system-workflows'])
            raise

    def heal(self, instance_id):
        self.logger.info('Healing node {0}...'.format(instance_id))
        self._cleanup_required = True
        try:
            self.cfy.executions.start.heal(
                ['-d', self.deployment_id,
                 '-p', 'node_instance_id={0}'.format(instance_id),
                 '-t', self.tenant])
        except Exception as e:
            if 'if there is a running system-wide' in e.message:
                self.logger.error('Error on deployment execution: %s', e)
                self.logger.info('Listing executions..')
                self.cfy.executions.list(['-d', self.deployment_id])
                self.cfy.executions.list(['--include-system-workflows'])
            raise

    def execute_hello_world_workflow(self, workflow_id):
        self.logger.info(
            'Executing workflow {0} on deployment {1} '
            'on a Regional cluster...'.format(
                workflow_id,
                constants.HELLO_WORLD_DEP)
        )
        workflow_params = {
            'workflow_id': workflow_id,
            'deployment_id': constants.HELLO_WORLD_DEP,
            'tenant_name': constants.TENANT_1
        }

        self.cfy.executions.start([
            'execute_workflow',
            '-d', self.deployment_id,
            '-p', json.dumps(workflow_params)
        ])
        self.logger.info(
            'Successfully executed workflow {0} on deployment {1} '
            'on a Regional cluster'.format(
                workflow_id,
                constants.HELLO_WORLD_DEP)
        )


class FixedIpRegionalCluster(AbstractRegionalCluster):
    TRANSFER_AGENTS = False
    RESOURCE_POOL0 = [
        {
            'ip_address': '10.0.0.45',
            'hostname': 'haproxy_0'
        },
        {
            'ip_address': '10.0.0.46',
            'hostname': 'haproxy_1'
        }
    ]
    RESOURCE_POOL1 = [
        {
            'ip_address': '10.0.0.47',
            'hostname': 'db_0'
        },
        {
            'ip_address': '10.0.0.48',
            'hostname': 'db_1'
        },
        {
            'ip_address': '10.0.0.49',
            'hostname': 'db_2'
        },
        {
            'ip_address': '10.0.0.50',
            'hostname': 'db_3'
        },
        {
            'ip_address': '10.0.0.51',
            'hostname': 'db_4'
        }
    ]
    RESOURCE_POOL2 = [
        {
            'ip_address': '10.0.0.52',
            'hostname': 'queue_0'
        },
        {
            'ip_address': '10.0.0.53',
            'hostname': 'queue_1'
        }
    ]
    RESOURCE_POOL3 = [
        {
            'ip_address': '10.0.0.54',
            'hostname': 'worker_0'
        },
        {
            'ip_address': '10.0.0.55',
            'hostname': 'worker_1'
        }
    ]

    @property
    def network_inputs(self):
        return {
            # Only relevant when working with the Private Fixed IP paradigm.
            # See more in private_fixed_ip.yaml
            'queue-infrastructure--'
            'resource_pool': self.RESOURCE_POOL2,
            'database-infrastructure--'
            'resource_pool': self.RESOURCE_POOL1,
            'worker-infrastructure--'
            'resource_pool': self.RESOURCE_POOL3,
            'haproxy-infrastructure--'
            'resource_pool': self.RESOURCE_POOL0,

        }

    @property
    def inputs(self):
        # To see explanations of the following inputs, see
        # https://github.com/cloudify-cosmo/cloudify-spire-plugin/
        # tree/master/blueprints/include
        inputs = self._base_inputs

        inputs.update(self.network_inputs)

        # When we are creating the initial cluster, we upload several
        # resources. In the next deployment, we will be restoring
        # from snapshot, so we expect those resources to already be
        # present.
        if self.first_deployment:
            additional_inputs = self._get_additional_resources_inputs()
        else:
            additional_inputs = self._get_upgrade_inputs()

        inputs.update(additional_inputs)

        return inputs

    def validate(self):
        pass

    def upload_blueprint(self, use_cfy=False):
        self.clone_example()
        namespace_blueprint_file = self._cloned_to / \
            'blueprints/infrastructure-examples/openstack/' \
            'fixed-private-ip-configuration.yaml'
        namespace_blueprint_id = 'infra'
        blueprint_file = self._cloned_to / self.blueprint_file

        self.logger.info('Uploading blueprint: %s [id=%s]',
                         namespace_blueprint_file,
                         namespace_blueprint_id)
        self.logger.info('Uploading blueprint: %s [id=%s]',
                         blueprint_file,
                         self.blueprint_id)

        if use_cfy:
            self.cfy.profile.set([
                '-t', self.tenant,
            ])
            self.cfy.blueprint.upload([
                '-b', namespace_blueprint_id,
                namespace_blueprint_file
            ])
            self.cfy.blueprint.upload([
                '-b', self.blueprint_id,
                blueprint_file
            ])
        else:
            if self.first_deployment:
                with util.set_client_tenant(self.manager, self.tenant):
                    self.manager.client.blueprints.upload(
                        namespace_blueprint_file, namespace_blueprint_id)
                    self.manager.client.blueprints.upload(
                        blueprint_file, self.blueprint_id)


class FloatingIpRegionalCluster(AbstractRegionalCluster):
    TRANSFER_AGENTS = True

    def __init__(self, *args, **kwargs):
        super(FloatingIpRegionalCluster, self).__init__(*args, **kwargs)
        self._central_client = None

    @property
    def network_inputs(self):
        # Only relevant when working with the Floating IP paradigm.
        # See more in floating_ip.yaml
        network_inputs = {}
        NET_1 = 'haproxy-infrastructure--os_floating_network'
        NET_2 = 'worker-infrastructure--os_floating_network'
        NET_3 = 'queue-infrastructure--os_floating_network'
        NET_4 = 'database-infrastructure--os_floating_network'
        ofn_keys = [NET_1, NET_2, NET_3, NET_4]
        for ofn_key in ofn_keys:
            network_inputs.update(
                {ofn_key: self.attributes.floating_network_id})
        return network_inputs

    @property
    def client(self):
        if not self._central_client:
            self._central_client = util.create_rest_client(
                manager_ip=self.cluster_endpoint,
                username=self.attributes.cloudify_username,
                password=self.attributes.cloudify_password,
                tenant=self.attributes.cloudify_tenant,
                protocol='https',
                cert=self._get_lb_cert()
            )

        return self._central_client

    @property
    def remote_lb_crt_path(self):
        # The location where the cert of the HAProxy saved after the HAProxy
        # configured to forward requests to cluster backend managers
        return '/etc/haproxy/cert.crt'

    @contextmanager
    def ssh(self):
        env = {
            'abort_exception': Exception,
            'disable_known_hosts': True,
            'host_string': self.cluster_endpoint,
            'gateway': self.cluster_endpoint,
            'user': self.manager.linux_username,
            'key_filename': self.ssh_key.private_key_path
        }
        with fabric_context_managers.settings(**env):
            yield fabric_api

    def _get_lb_cert(self):
        local_cert = str(self.tmpdir / 'ca_cert.pem')
        with self.ssh() as fabric_ssh:
            with fabric_ssh.show('debug'):
                fabric_ssh.get(
                    self.remote_lb_crt_path,
                    local_cert,
                    use_sudo=True
                )
        return local_cert

    def validate(self):
        """
        For Floating IP clusters validation involves creating a REST client
        to connect to the master manager, and making sure that certain
        Cloudify resources (tenants, plugins, etc) were created
        """
        self._validate_tenants_created()
        self._validate_blueprints_created()
        self._validate_deployments_created()
        self._validate_secrets_created()
        self._validate_plugins_created()

    def _validate_tenants_created(self):
        self.logger.info(
            'Validating that tenants were created on Regional cluster...'
        )
        tenants = self.client.tenants.list(_include=['name'])
        tenant_names = {t['name'] for t in tenants}
        assert tenant_names == {DEFAULT_TENANT_NAME,
                                constants.TENANT_1,
                                constants.TENANT_2}
        self.logger.info('Tenants validated successfully')

    def _validate_blueprints_created(self):
        self.logger.info(
            'Validating that blueprints were created on Regional cluster...'
        )
        blueprints = self.client.blueprints.list(
            _all_tenants=True,
            _include=['id', 'tenant_name']
        )
        blueprint_pairs = {(b['id'], b['tenant_name']) for b in blueprints}
        assert blueprint_pairs == {
            (constants.HELLO_WORLD_BP, constants.TENANT_1)
        }
        self.logger.info('Blueprints validated successfully')

    def _validate_deployments_created(self):
        self.logger.info(
            'Validating that deployments were created on Regional cluster...'
        )
        deployments = self.client.deployments.list(
            _all_tenants=True,
            _include=['id', 'blueprint_id']
        )
        assert len(deployments) == 1
        deployment = deployments[0]
        assert deployment.id == constants.HELLO_WORLD_DEP
        assert deployment.blueprint_id == constants.HELLO_WORLD_BP

        self.logger.info('Deployments validated successfully')

    def _validate_secrets_created(self):
        self.logger.info(
            'Validating that secrets were created on Regional cluster...'
        )
        secrets = self.client.secrets.list(_all_tenants=True)
        secrets = {s['key']: s for s in secrets}

        expected_set = {constants.SECRET_FILE_KEY, constants.SECRET_STRING_KEY}

        # During upgrade we add secrets for ssh keys, so the actual set might
        # not be equal exactly, but may contain extra values
        assert set(secrets.keys()).issuperset(expected_set)

        tenant = secrets[constants.SECRET_STRING_KEY]['tenant_name']

        # Temporarily change the tenant in the REST client, to access a secret
        # on this tenant
        with util.set_client_tenant(self, tenant):
            string_secret_value = self.client.secrets.get(
                constants.SECRET_STRING_KEY).value
            assert string_secret_value == constants.SECRET_STRING_VALUE
        self.logger.info('Secrets validated successfully')

    def _validate_plugins_created(self):
        self.logger.info(
            'Validating that plugins were created on Regional cluster...'
        )

        plugins = self.client.plugins.list(_all_tenants=True)
        assert len(plugins) == 3

        self.logger.info('Plugins validated successfully')
