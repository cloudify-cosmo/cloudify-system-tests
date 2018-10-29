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
import yaml
from time import sleep

import pytest

from cloudify_cli.constants import DEFAULT_TENANT_NAME

from cosmo_tester.framework import util
from cosmo_tester.framework.test_hosts import TestHosts
from cosmo_tester.framework.examples import AbstractExample
from cosmo_tester.test_suites.snapshots import restore_snapshot

MOM_PLUGIN_VERSION = '1.5.6'
MOM_PLUGIN_WGN_URL = 'https://github.com/Cloudify-PS/manager-of-managers/releases/download/v{0}/cloudify_manager_of_managers-{0}-py27-none-linux_x86_64.wgn'.format(MOM_PLUGIN_VERSION)  # NOQA
MOM_PLUGIN_YAML_URL = 'https://github.com/Cloudify-PS/manager-of-managers/releases/download/v{0}/cmom_plugin.yaml'.format(MOM_PLUGIN_VERSION)  # NOQA

# This version of the plugin is used by the mom blueprint
OS_PLUGIN_VERSION = '2.12.0'
OS_PLUGIN_WGN_FILENAME = 'cloudify_openstack_plugin-{0}-py27-none-linux_x86_64-centos-Core.wgn'.format(OS_PLUGIN_VERSION)  # NOQA
OS_PLUGIN_WGN_URL = 'http://repository.cloudifysource.org/cloudify/wagons/cloudify-openstack-plugin/{0}/{1}'.format(OS_PLUGIN_VERSION, OS_PLUGIN_WGN_FILENAME)  # NOQA
OS_PLUGIN_YAML_URL = 'http://www.getcloudify.org/spec/openstack-plugin/{0}/plugin.yaml'.format(OS_PLUGIN_VERSION)  # NOQA

# Using 2.0.1 because this is what the hello world blueprint is using
OS_201_PLUGIN_WGN_URL = 'http://repository.cloudifysource.org/cloudify/wagons/cloudify-openstack-plugin/2.0.1/cloudify_openstack_plugin-2.0.1-py27-none-linux_x86_64-centos-Core.wgn'  # NOQA
OS_201_PLUGIN_YAML_URL = 'http://www.getcloudify.org/spec/openstack-plugin/2.0.1/plugin.yaml'  # NOQA

HELLO_WORLD_URL = 'https://github.com/cloudify-cosmo/cloudify-hello-world-example/archive/4.5.zip'  # NOQA

TENANT_1 = 'tenant_1'
TENANT_2 = 'tenant_2'

TIER_2_SNAP_ID = 'snapshot_id'

INSTALL_RPM_PATH = '/etc/cloudify/cloudify-manager-install.rpm'
PLUGIN_WGN_PATH = '/etc/cloudify/{0}'.format(OS_PLUGIN_WGN_FILENAME)
PLUGIN_YAML_PATH = '/etc/cloudify/plugin.yaml'

SECRET_STRING_KEY = 'test_secret_from_string'
SECRET_STRING_VALUE = 'test_secret_value'
SECRET_FILE_KEY = 'test_secret_from_file'

BLUEPRINT_ZIP_PATH = '/etc/cloudify/cloudify-hello-world-example.zip'

SCRIPT_SH_PATH = '/etc/cloudify/script_1.sh'
SCRIPT_PY_PATH = '/etc/cloudify/script_2.py'

SH_SCRIPT = '''#!/usr/bin/env bash
echo "Running a bash script!"
'''

PY_SCRIPT = '''#!/usr/bin/env python
print 'Running a python script!'
'''


class AbstractTier1Cluster(AbstractExample):
    REPOSITORY_URL = 'https://github.com/Cloudify-PS/manager-of-managers.git'  # NOQA

    @property
    def inputs(self):
        openstack_config = util.get_openstack_config()

        device_mapping_config = {
            'boot_index': '0',
            'uuid': self.attributes.default_linux_image_id,
            'volume_size': 30,
            'source_type': 'image',
            'destination_type': 'volume',
            'delete_on_termination': True
        }

        inputs = {
            'os_password': openstack_config['password'],
            'os_username': openstack_config['username'],
            'os_tenant': openstack_config['tenant_name'],
            'os_auth_url': openstack_config['auth_url'],
            'os_region': os.environ['OS_REGION_NAME'],

            'os_image': '',
            'os_flavor': self.attributes.manager_server_flavor_name,
            'os_device_mapping': [device_mapping_config],
            'os_network': self.attributes.network_name,
            'os_subnet': self.attributes.subnet_name,
            'os_keypair': self.attributes.keypair_name,
            'os_security_group': self.attributes.security_group_name,

            'ssh_user': self.attributes.default_linux_username,
            'ssh_private_key_path': self.manager.remote_private_key_path,

            'ca_cert': self.attributes.LOCAL_REST_CERT_FILE,
            'ca_key': self.attributes.LOCAL_REST_KEY_FILE,
            'install_rpm_path': INSTALL_RPM_PATH,
            'manager_admin_password': self.attributes.cloudify_password,

            'num_of_instances': 2,

            # Config in the same format as config.yaml
            # Skipping sanity to save time
            'additional_config': {'sanity': {'skip_sanity': True}}
        }

        inputs.update(self.network_inputs)

        if self.first_deployment:
            additional_inputs = {
                'tenants': [TENANT_1, TENANT_2],
                'plugins': [
                    {
                        'wagon': PLUGIN_WGN_PATH,
                        'yaml': PLUGIN_YAML_PATH,
                        'tenant': TENANT_1
                    }
                ],
                'secrets': [
                    {
                        'key': SECRET_STRING_KEY,
                        'string': SECRET_STRING_VALUE,
                        'tenant': TENANT_2
                    },
                    {
                        'key': SECRET_FILE_KEY,
                        'file': SCRIPT_PY_PATH,
                        'visibility': 'global'
                    }
                ],
                'blueprints': [
                    {
                        'path': BLUEPRINT_ZIP_PATH,
                        'filename': 'no-monitoring-singlehost-blueprint.yaml'
                    },
                    {
                        'path': BLUEPRINT_ZIP_PATH,
                        'id': 'second_bp',
                        'filename': 'singlehost-blueprint.yaml',
                        'tenant': TENANT_2
                    },
                    {
                        'path': BLUEPRINT_ZIP_PATH,
                        'id': 'third_bp',
                        'filename': 'openstack-blueprint.yaml',
                        'tenant': TENANT_1,
                        'visibility': 'global'
                    }
                ],
                'scripts': [SCRIPT_SH_PATH, SCRIPT_PY_PATH],
                'files': [
                    {
                        'src': PLUGIN_YAML_PATH,
                        'dst': '/tmp/plugin.yaml'
                    },
                    {
                        'src': SCRIPT_PY_PATH,
                        'dst': '/tmp/script.py'
                    }
                ]
            }
        else:
            # A trick to get the deployment ID of the first cluster
            old_deployment_id = self.deployment_id.replace('1', '0')
            additional_inputs = {
                'restore': True,
                'old_deployment_id': old_deployment_id,
                'snapshot_id': old_deployment_id,
                # TODO: Test _with_ agents
                'transfer_agents': False
            }

        inputs.update(additional_inputs)
        return inputs

    @property
    def network_inputs(self):
        raise NotImplementedError('Each Tier 1 Cluster class needs to '
                                  'add additional network inputs')

    def validate(self):
        raise NotImplementedError('Each Tier 1 Cluster class needs to '
                                  'implement the `validate` method')

    @property
    def first_deployment(self):
        """
        Indicate that this is the initial deployment, as opposed to the second
        one, to which we will upgrade
        """
        return '0' in self.deployment_id

    def upload_blueprint(self):
        # We only want to upload the blueprint once, but create several deps
        if self.first_deployment:
            super(AbstractTier1Cluster, self).upload_blueprint()

    def install(self):
        super(AbstractTier1Cluster, self).install()
        self._populate_status_output()

    def _populate_status_output(self):
        # This workflow populates the deployment outputs with status info
        self.cfy.executions.start('get_status', '-d', self.deployment_id)
        self.cfy.deployments.outputs(self.deployment_id)

    def verify_installation(self):
        super(AbstractTier1Cluster, self).verify_installation()

        cluster_status = self.outputs['cluster_status']
        for service in cluster_status['leader_status']:
            assert service['status'] == 'running'

        for tier_1_manager in cluster_status['cluster_status']:
            for check in ('cloudify services', 'consul',
                          'database', 'heartbeat'):
                assert tier_1_manager[check] == 'OK'

    def deploy_and_validate(self):
        self.logger.info(
            'Deploying Tier 1 cluster on deployment: {0}'.format(
                self.deployment_id
            )
        )
        self.upload_and_verify_install()
        self.validate()

    def backup(self):
        self.logger.info(
            'Running backup workflow on Tier 1 cluster on dep: {0}...'.format(
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


# Using function scope here, in order to have a clean Tier 2 manager each time
@pytest.fixture(scope='function')
def tier_2_manager(cfy, ssh_key, module_tmpdir, attributes, logger):
    """
    Creates a Tier 2 Cloudify manager with all the necessary resources on it
    """
    hosts = TestHosts(
            cfy, ssh_key, module_tmpdir, attributes, logger)
    try:
        hosts.create()
        manager = hosts.instances[0]
        manager.use()
        _upload_resources_to_tier_2_manager(manager, logger)
        yield manager
    finally:
        hosts.destroy()


def _upload_resources_to_tier_2_manager(manager, logger):
    manager.client.plugins.upload(MOM_PLUGIN_WGN_URL, MOM_PLUGIN_YAML_URL)
    manager.client.plugins.upload(OS_PLUGIN_WGN_URL, OS_PLUGIN_YAML_URL)

    files_to_download = [
        (util.get_manager_install_rpm_url(), INSTALL_RPM_PATH),
        (OS_201_PLUGIN_WGN_URL, PLUGIN_WGN_PATH),
        (OS_201_PLUGIN_YAML_URL, PLUGIN_YAML_PATH),
        (HELLO_WORLD_URL, BLUEPRINT_ZIP_PATH)
    ]
    files_to_create = [
        (SH_SCRIPT, SCRIPT_SH_PATH),
        (PY_SCRIPT, SCRIPT_PY_PATH)
    ]

    logger.info('Downloading necessary files to the Tier 2 manager...')
    for src_url, dst_path in files_to_download:
        manager.run_command(
            'curl -L {0} -o {1}'.format(src_url, dst_path),
            use_sudo=True
        )

    for src_content, dst_path in files_to_create:
        manager.put_remote_file_content(dst_path, src_content, use_sudo=True)

    logger.info('Giving `cfyuser` permissions to downloaded files...')
    for _, dst_path in files_to_download + files_to_create:
        manager.run_command(
            'chown cfyuser:cfyuser {0}'.format(dst_path),
            use_sudo=True
        )


class FixedIpTier1Cluster(AbstractTier1Cluster):
    RESOURCE_POOLS = [
        {
            'ip_address': '10.0.0.11',
            'hostname': 'Tier_1_Manager_1'
        },
        {
            'ip_address': '10.0.0.12',
            'hostname': 'Tier_1_Manager_2'
        }
    ]

    @property
    def network_inputs(self):
        return {
            # Only relevant when working with the Private Fixed IP paradigm.
            # See more in private_fixed_ip.yaml
            'resource_pool': self.RESOURCE_POOLS
        }

    def validate(self):
        cluster_ips = self.outputs['cluster_ips']
        actual_ips = set(cluster_ips['Slaves'] + [cluster_ips['Master']])

        fixed_ips = {r['ip_address'] for r in self.RESOURCE_POOLS}

        assert actual_ips == fixed_ips


@pytest.fixture(scope='module')
def fixed_ip_2_tier_1_clusters(cfy, tier_2_manager,
                               attributes, ssh_key, module_tmpdir, logger):
    """ Yield 2 Tier 1 clusters set up with fixed private IPs """

    clusters = _get_tier_1_clusters(
        'cfy_manager_fixed_ip',
        2,
        FixedIpTier1Cluster,
        cfy, logger, module_tmpdir, attributes, ssh_key, tier_2_manager
    )

    yield clusters
    for cluster in clusters:
        cluster.cleanup()


def _get_tier_1_clusters(resource_id, number_of_deps, cluster_class,
                         cfy, logger, tmpdir, attributes, ssh_key,
                         tier_2_manager):
    clusters = []

    for i in range(number_of_deps):
        cluster = cluster_class(
            cfy, tier_2_manager, attributes,
            ssh_key, logger, tmpdir, suffix=resource_id
        )
        cluster.blueprint_id = '{0}_bp'.format(resource_id)
        cluster.deployment_id = '{0}_dep_{1}'.format(resource_id, i)
        cluster.blueprint_file = 'blueprint.yaml'
        clusters.append(cluster)

    return clusters


