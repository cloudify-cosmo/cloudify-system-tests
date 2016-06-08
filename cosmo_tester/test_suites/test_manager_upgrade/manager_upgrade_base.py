########
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
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

from contextlib import contextmanager
import json
import os
import shutil
import tempfile
import time
import urllib2

from distutils.version import LooseVersion
import fabric
from influxdb import InfluxDBClient

from cloudify_cli import constants as cli_constants
from cloudify.workflows import local

from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.git_helper import clone
from cosmo_tester.framework.cfy_helper import CfyHelper

from cosmo_tester.framework.util import create_rest_client, YamlPatcher


BOOTSTRAP_REPO_URL = 'https://github.com/cloudify-cosmo/' \
                     'cloudify-manager-blueprints.git'
BOOTSTRAP_BRANCH = '3.4m5'

UPGRADE_REPO_URL = 'https://github.com/cloudify-cosmo/' \
                   'cloudify-manager-blueprints.git'
UPGRADE_BRANCH = 'master'


class BaseManagerUpgradeTest(TestCase):

    @contextmanager
    def _manager_fabric_env(self):
        inputs = self.manager_inputs
        with fabric.context_managers.settings(
                host_string=self.upgrade_manager_ip,
                user=inputs['ssh_user'],
                key_filename=inputs['ssh_key_filename']):
            yield fabric.api

    def _bootstrap_local_env(self, workdir):
        storage = local.FileStorage(
                os.path.join(workdir, '.cloudify', 'bootstrap'))
        return local.load_env('manager', storage=storage)

    def _blueprint_rpm_versions(self, blueprint_path, inputs):
        """RPM filenames that should be installed on the manager.
        """
        env = local.init_env(
                blueprint_path,
                inputs=inputs,
                ignored_modules=cli_constants.IGNORED_LOCAL_WORKFLOW_MODULES)

        storage = env.storage

        amqp_influx_rpm = storage.get_node('amqp_influx')['properties'][
            'amqpinflux_rpm_source_url']
        restservice_rpm = storage.get_node('rest_service')['properties'][
            'rest_service_rpm_source_url']
        mgmtworker_rpm = storage.get_node('mgmt_worker')['properties'][
            'management_worker_rpm_source_url']
        return {
            'cloudify-amqp-influx': amqp_influx_rpm,
            'cloudify-rest-service': restservice_rpm,
            'cloudify-management-worker': mgmtworker_rpm
        }

    def _cloudify_rpm_versions(self):
        with self._manager_fabric_env() as fabric:
            return fabric.sudo('rpm -qa | grep cloudify')

    def check_rpm_versions(self, blueprint_path, inputs):
        blueprint_rpms = self._blueprint_rpm_versions(blueprint_path, inputs)
        installed_rpms = self._cloudify_rpm_versions()
        for service_name, rpm_filename in blueprint_rpms.items():
            for line in installed_rpms.split('\n'):
                line = line.strip()
                if line.startswith(service_name):
                    self.assertIn(line.strip(), rpm_filename)

    def prepare_manager(self):
        # note that we're using a separate manager checkout, so we need to
        # create our own utils like cfy and the rest client, rather than use
        # the testenv ones
        self.cfy_workdir = tempfile.mkdtemp(prefix='manager-upgrade-')
        self.addCleanup(shutil.rmtree, self.cfy_workdir)
        self.manager_cfy = CfyHelper(cfy_workdir=self.cfy_workdir)

        self.manager_inputs = self._get_bootstrap_inputs()

        self.bootstrap_manager()

        self.rest_client = create_rest_client(self.upgrade_manager_ip)

        self.bootstrap_manager_version = LooseVersion(
                self.rest_client.manager.get_version()['version'])

    def _get_bootstrap_inputs(self):
        prefix = self.test_id

        ssh_key_filename = os.path.join(self.workdir, 'manager.key')
        self.addCleanup(self.env.handler.remove_keypair,
                        prefix + '-manager-key')

        agent_key_path = os.path.join(self.workdir, 'agents.key')
        self.addCleanup(self.env.handler.remove_keypair,
                        prefix + '-agents-key')

        return {
            'keystone_username': self.env.keystone_username,
            'keystone_password': self.env.keystone_password,
            'keystone_tenant_name': self.env.keystone_tenant_name,
            'keystone_url': self.env.keystone_url,
            'region': self.env.region,
            'flavor_id': self.env.medium_flavor_id,
            'image_id': self.env.centos_7_image_id,

            'ssh_user': self.env.centos_7_image_user,
            'external_network_name': self.env.external_network_name,
            'resources_prefix': 'test-upgrade-',

            'manager_server_name': prefix + '-manager',

            # shared settings
            'manager_public_key_name': prefix + '-manager-key',
            'agent_public_key_name': prefix + '-agents-key',
            'ssh_key_filename': ssh_key_filename,
            'agent_private_key_path': agent_key_path,

            'management_network_name': prefix + '-network',
            'management_subnet_name': prefix + '-subnet',
            'management_router': prefix + '-router',

            'agents_user': '',

            # private settings
            'manager_security_group_name': prefix + '-m-sg',
            'agents_security_group_name': prefix + '-a-sg',
            'manager_port_name': prefix + '-port',
            'management_subnet_dns_nameservers': ['8.8.8.8', '8.8.4.4']
        }

    def get_bootstrap_blueprint(self):
        manager_repo_dir = tempfile.mkdtemp(prefix='manager-upgrade-')
        self.addCleanup(shutil.rmtree, manager_repo_dir)
        manager_repo = clone(BOOTSTRAP_REPO_URL,
                             manager_repo_dir,
                             branch=BOOTSTRAP_BRANCH)
        yaml_path = manager_repo / 'openstack-manager-blueprint.yaml'

        # allow the ports that we're going to connect to from the tests,
        # when doing checks
        for port in [8086, 9200, 9900]:
            secgroup_cfg = [{
                'port_range_min': port,
                'port_range_max': port,
                'remote_ip_prefix': '0.0.0.0/0'
            }]
            secgroup_cfg_path = 'node_templates.management_security_group' \
                                '.properties.rules'
            with YamlPatcher(yaml_path) as patch:
                patch.append_value(secgroup_cfg_path, secgroup_cfg)

        return yaml_path

    def _load_private_ip_from_env(self, workdir):
        env = self._bootstrap_local_env(workdir)
        return env.outputs()['private_ip']

    def bootstrap_manager(self):
        self.bootstrap_blueprint = self.get_bootstrap_blueprint()
        inputs_path = self.manager_cfy._get_inputs_in_temp_file(
                self.manager_inputs, self._testMethodName)

        self.manager_cfy.bootstrap(self.bootstrap_blueprint,
                                   inputs_file=inputs_path)

        self.upgrade_manager_ip = self.manager_cfy.get_management_ip()
        self.manager_private_ip = self._load_private_ip_from_env(
                self.cfy_workdir)

        # TODO: why is this needed?
        self.manager_cfy.use(management_ip=self.upgrade_manager_ip)

    def deploy_hello_world(self, prefix=''):
        """Install the hello world app."""
        blueprint_id = prefix + self.test_id
        deployment_id = prefix + self.test_id
        hello_repo_dir = tempfile.mkdtemp(prefix='manager-upgrade-')
        hello_repo_path = clone(
                'https://github.com/cloudify-cosmo/'
                'cloudify-hello-world-example.git',
                hello_repo_dir
        )
        self.addCleanup(shutil.rmtree, hello_repo_dir)
        hello_blueprint_path = hello_repo_path / 'blueprint.yaml'
        self.manager_cfy.upload_blueprint(blueprint_id, hello_blueprint_path)

        inputs = {
            'agent_user': self.env.ubuntu_image_user,
            'image': self.env.ubuntu_trusty_image_name,
            'flavor': self.env.flavor_name
        }
        self.manager_cfy.create_deployment(blueprint_id, deployment_id,
                                           inputs=inputs)

        self.manager_cfy.execute_install(deployment_id=deployment_id)
        return deployment_id

    def get_upgrade_blueprint(self):
        repo_dir = tempfile.mkdtemp(prefix='manager-upgrade-')
        self.addCleanup(shutil.rmtree, repo_dir)
        upgrade_blueprint_path = clone(UPGRADE_REPO_URL,
                                       repo_dir,
                                       branch=UPGRADE_BRANCH)

        return upgrade_blueprint_path / 'simple-manager-blueprint.yaml'

    def upgrade_manager(self, blueprint=None, inputs=None):
        self.upgrade_blueprint = blueprint or self.get_upgrade_blueprint()
        if not blueprint:
            # we're changing one of the ES inputs -
            # make sure we also re-install ES
            with YamlPatcher(self.upgrade_blueprint) as patch:
                patch.set_value(
                        ('node_templates.elasticsearch.properties'
                         '.use_existing_on_upgrade'),
                        False)

        self.upgrade_inputs = inputs or {
            'private_ip': self.manager_private_ip,
            'public_ip': self.upgrade_manager_ip,
            'ssh_key_filename': self.manager_inputs['ssh_key_filename'],
            'ssh_user': self.manager_inputs['ssh_user'],
            'elasticsearch_endpoint_port': 9900

        }
        upgrade_inputs_file = self.manager_cfy._get_inputs_in_temp_file(
                self.upgrade_inputs, self._testMethodName)

        with self.manager_cfy.maintenance_mode():
            self.manager_cfy.upgrade_manager(
                    blueprint_path=self.upgrade_blueprint,
                    inputs_file=upgrade_inputs_file)

    def post_upgrade_checks(self, preupgrade_deployment_id):
        """To check if the upgrade succeeded:
            - fire a request to the REST service
            - check that elasticsearch is listening on the changed port
            - check that the pre-existing deployment still reports to influxdb
            - install a new deployment, check that it reports to influxdb,
              and uninstall it: to check that the manager still allows
              creating, installing and uninstalling deployments correctly
        """
        upgrade_manager_version = LooseVersion(
                self.rest_client.manager.get_version()['version'])
        self.assertGreaterEqual(upgrade_manager_version,
                                self.bootstrap_manager_version)
        self.check_rpm_versions(self.upgrade_blueprint, self.upgrade_inputs)

        self.rest_client.blueprints.list()
        self.check_elasticsearch(self.upgrade_manager_ip, 9900)
        self.check_influx(preupgrade_deployment_id)

        postupgrade_deployment_id = self.deploy_hello_world('post-')
        self.check_influx(postupgrade_deployment_id)
        self.uninstall_deployment(postupgrade_deployment_id)

    def check_influx(self, deployment_id):
        """Check that the deployment_id continues to report metrics.

        Look at the last 5 seconds worth of metrics. To avoid race conditions
        (running this check before the deployment even had a chance to report
        any metrics), first wait 5 seconds to allow some metrics to be
        gathered.
        """
        # TODO influx config should be pulled from props?
        time.sleep(5)
        influx_client = InfluxDBClient(self.upgrade_manager_ip, 8086,
                                       'root', 'root', 'cloudify')
        try:
            result = influx_client.query('select * from /^{0}\./i '
                                         'where time > now() - 5s'
                                         .format(deployment_id))
        except NameError as e:
            self.fail('monitoring events list for deployment with ID {0} were'
                      ' not found on influxDB. error is: {1}'
                      .format(deployment_id, e))

        self.assertTrue(len(result) > 0)

    def check_elasticsearch(self, host, port):
        """Check that elasticsearch is listening on the given host:port.

        This is used for checking if the ES port changed correctly during
        the upgrade.
        """
        try:
            response = urllib2.urlopen('http://{0}:{1}'.format(
                    self.upgrade_manager_ip, port))
            response = json.load(response)
            if response['status'] != 200:
                raise ValueError('Incorrect status {0}'.format(
                        response['status']))
        except (ValueError, urllib2.URLError):
            self.fail('elasticsearch isnt listening on the changed port')

    def uninstall_deployment(self, deployment_id):
        self.manager_cfy.execute_uninstall(deployment_id)

    def rollback_manager(self):
        rollback_inputs = {
            'private_ip': self.manager_private_ip,
            'public_ip': self.upgrade_manager_ip,
            'ssh_key_filename': self.manager_inputs['ssh_key_filename'],
            'ssh_user': self.manager_inputs['ssh_user'],
        }
        rollback_inputs_file = self.manager_cfy._get_inputs_in_temp_file(
                rollback_inputs, self._testMethodName)

        with self.manager_cfy.maintenance_mode():
            self.manager_cfy.rollback_manager(
                    blueprint_path=self.upgrade_blueprint,
                    inputs_file=rollback_inputs_file)

    def post_rollback_checks(self, preupgrade_deployment_id):
        rollback_manager_version = LooseVersion(
                self.rest_client.manager.get_version()['version'])
        self.assertEqual(rollback_manager_version,
                         self.bootstrap_manager_version)
        self.check_rpm_versions(self.bootstrap_blueprint, self.manager_inputs)

        self.rest_client.blueprints.list()
        self.check_elasticsearch(self.upgrade_manager_ip, 9200)
        self.check_influx(preupgrade_deployment_id)

    def teardown_manager(self):
        self.manager_cfy.teardown(ignore_deployments=True)
