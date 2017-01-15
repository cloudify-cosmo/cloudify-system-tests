########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# * See the License for the specific language governing permissions and
#    * limitations under the License.
import os
import json
import time
import copy
import re
import uuid
from contextlib import contextmanager

import requests
from retrying import retry
import sh
import yaml

import fabric.api as fab
from cloudify.workflows import local
from cloudify_cli import constants as cli_constants
from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework import util
from fabric.context_managers import settings as fab_env, cd


# The cfy helper doesn't provide an init method, so we'll do it ourselves
cfy = util.sh_bake(sh.cfy)

# If we get a recycled floating IP we'll have a bad day without this
fab.env['disable_known_hosts'] = True

CHECK_URL = 'www.google.com'
HELLO_WORLD_EXAMPLE_NAME = 'cloudify-hello-world-example'
EXAMPLE_URL = 'https://github.com/cloudify-cosmo/{0}/archive/{1}.tar.gz'


class FabException(Exception):
    """
    Custom exception which replaces the standard SystemExit which is raised
    by fabric on errors.
    """
    pass


class TestCliPackage(TestCase):

    @property
    def package_parameter_name(self):
        raise NotImplementedError

    @property
    def cli_package_url(self):
        return os.environ[self.package_parameter_name]

    @property
    def client_cfy_work_dir(self):
        raise NotImplementedError

    @property
    def client_user(self):
        return 'centos'

    @property
    def image_name(self):
        raise NotImplementedError

    @property
    def manager_blueprint_file_name(self):
        raise NotImplementedError

    @property
    def local_env_blueprint_file_name(self):
        raise NotImplementedError

    @property
    def local_env_inputs(self):
        raise NotImplementedError

    @property
    def bootstrap_inputs(self):
        raise NotImplementedError

    @property
    def deployment_inputs(self):
        raise NotImplementedError

    @property
    def app_blueprint_file(self):
        raise NotImplementedError

    @property
    def iaas_url(self):
        raise NotImplementedError

    @property
    def client_executor(self):
        return self._execute_command_on_linux

    @property
    def manager_executor(self):
        return self._execute_command_on_linux

    @property
    def manager_username(self):
        return 'admin'

    @property
    def manager_password(self):
        return 'admin'

    @property
    def helloworld_url(self):
        return EXAMPLE_URL.format(HELLO_WORLD_EXAMPLE_NAME, self.branch)

    def get_local_env_outputs(self):
        self.public_ip_address = \
            self.local_env.outputs()['vm_public_ip_address']

    def is_install_plugins(self):
        return False

    def additional_setup(self):
        if self.package_parameter_name not in os.environ:
            raise ValueError(
                '{0} environment variable not set'
                .format(self.package_parameter_name))

        blueprint_filename = self.local_env_blueprint_file_name
        relative_blueprint_path = os.path.join('blueprints',
                                               'cli',
                                               blueprint_filename)
        blueprint_path = util.get_resource_path(relative_blueprint_path)

        self.test_id = 'stest-{0}'.format(
            time.strftime("%Y%m%d-%H%M"))
        self.prefix = '{0}-cli-host'.format(self.test_id)
        self.bootstrap_prefix = 'cloudify-{0}'.format(self.test_id)

        self.branch = os.environ.get('BRANCH_NAME_CORE', 'master')
        self.logger.info('Using branch/tag: {0}'.format(self.branch))

        self.logger.info('initialize local env for running the '
                         'blueprint that starts a vm')
        self.local_env = local.init_env(
            blueprint_path,
            inputs=self.local_env_inputs,
            name=self._testMethodName,
            ignored_modules=cli_constants.IGNORED_LOCAL_WORKFLOW_MODULES)

        self.logger.info('Starting vm to install CLI package on it later on')
        self.addCleanup(self.cleanup)
        self.local_env.execute('install',
                               task_retries=40,
                               task_retry_interval=30)

        self.get_local_env_outputs()
        self.logger.info('Outputs: {0}'.format(self.local_env.outputs()))

        self.centos_client_env = {
            'timeout': 30,
            'user': self.client_user,
            'key_filename': self.local_env_inputs['key_pair_path'],
            'host_string': self.public_ip_address,
            'connection_attempts': 10,
            'abort_on_prompts': True,
            'abort_exception': Exception
        }

        self.verify_connection()
        # Since different IAAS providers enable some default DNS which enables
        # internet access, by this call we make sure that all of the tests
        # begin with no dns based internet connection. In online tests, the
        # dns is being set by the dns() context manager.
        self.go_offline(self.centos_client_env)

    def setUp(self):
        super(TestCliPackage, self).setUp()
        self.additional_setup()

    def verify_connection(self):
        # Make sure cli machine ready for incoming connections
        wait_for_connection(self.centos_client_env,
                            self.client_executor,
                            self.logger)

    def _execute_command_on_linux(
            self,
            cmd,
            fabric_env=None,
            within_cfy_env=False,
            sudo=False,
            log_cmd=True,
            retries=0,
            warn_only=False):

        if not fabric_env:
            fabric_env = self.centos_client_env
        if within_cfy_env:
            cmd = 'cfy {0}'.format(cmd)

        if log_cmd:
            self.logger.info('Executing command: {0}'.format(cmd))
        else:
            self.logger.info('Executing command: ***')

        while True:
            with fab_env(**fabric_env):
                if sudo:
                    out = fab.sudo(cmd, warn_only=warn_only)
                else:
                    out = fab.run(cmd, warn_only=warn_only)

            self.logger.info("""Command execution result:
    Status code: {0}
    STDOUT:
    {1}
    STDERR:
    {2}""".format(out.return_code, out, out.stderr))
            if out.succeeded or (warn_only and retries == 0):
                return out
            else:
                if retries > 0:
                    time.sleep(30)
                    retries -= 1
                else:
                    raise Exception('Command: {0} exited with code: '
                                    '{1}. Tried {2} times.'
                                    .format(cmd, out.return_code, retries + 1))

    def prepare_cli(self):
        self.logger.info('installing cli...')
        self._get_resource(self.cli_package_url, curl_ops='-LO', sudo=True)

    def install_cli(self, *args, **kwargs):
        last_ind = self.cli_package_url.rindex('/')
        package_name = self.cli_package_url[last_ind + 1:]
        self.client_executor('rpm -i {0} || dpkg -i {0}'.format(package_name),
                             self.centos_client_env,
                             sudo=True)

    def _get_resource(self, resource_address, sudo=False, curl_ops='',
                      *args, **kwargs):

        return self.client_executor(
            'curl {0} {1}'.format(resource_address, curl_ops),
            self.centos_client_env,
            sudo=sudo)

    def add_dns_nameservers_to_manager_blueprint(self, local_modify_script):
        remote_modify_script = os.path.join(self.client_cfy_work_dir,
                                            'modify.py')
        self.logger.info(
            'Uploading {0} to {1} on manager...'.format(local_modify_script,
                                                        remote_modify_script))
        with fab_env(**self.centos_client_env):
            fab.put(local_modify_script, remote_modify_script, use_sudo=True)
            self.logger.info(
                'Adding DNS name servers to remote manager blueprint...')
            fab.run('sudo python {0} {1}'.format(
                remote_modify_script, self.manager_blueprint_path))

    def prepare_manager_blueprint(self):
        self.logger.info('Preparing manager blueprint')
        self.manager_blueprints_dir = \
            '{0}/cloudify-manager-blueprints'.format(
                self.client_cfy_work_dir)
        self.manager_blueprint_path = \
            os.path.join(self.manager_blueprints_dir,
                         self.manager_blueprint_file_name)

    def write_file_remotely(self, local_file_path, remote_file_path, env=None,
                            sudo=False, **kwargs):
        env = env or self.centos_client_env
        with fab_env(**env):
            fab.put(local_file_path, remote_file_path, use_sudo=sudo)

    def create_inputs_file(self, inputs, inputs_file_name):
        inputs = self._update_username_password_inputs(inputs)
        local_inputs_path = self.get_inputs_in_temp_file(
            inputs,
            self._testMethodName)
        remote_inputs_path = os.path.join(
            self.client_cfy_work_dir,
            '{0}.yaml'.format(inputs_file_name))
        self.write_file_remotely(local_inputs_path, remote_inputs_path,
                                 sudo=True)
        return remote_inputs_path

    def _update_username_password_inputs(self, inputs):
        new_inputs = copy.deepcopy(inputs)
        new_inputs['admin_username'] = self.manager_username
        new_inputs['admin_password'] = self.manager_password
        return new_inputs

    def prepare_inputs_and_bootstrap(self, inputs):
        # using inputs file and not passing all inputs in the cmd line
        # prevents "The command line is too long" in windows.
        bootstrap_inputs_path = self.create_inputs_file(
            inputs,
            'bootstrap_inputs')
        self.bootstrap_manager(bootstrap_inputs_path, inputs_is_file=True)

    def bootstrap_manager(self,
                          inputs,
                          inputs_is_file=False):
        self.logger.info('Bootstrapping Cloudify manager...')
        self.client_executor(
            'init',
            fabric_env=self.centos_client_env,
            within_cfy_env=True)

        install_plugins = ''
        if self.is_install_plugins():
            install_plugins = '--install-plugins'

        bootstrap_command = \
            "bootstrap --skip-validations {0} -i \"{1}\" {2}".format(
                install_plugins,
                json.dumps(inputs).replace('"', "'").replace(' ', ''),
                self.manager_blueprint_path)
        if inputs_is_file:
            bootstrap_command = \
                "bootstrap --skip-validations {0} -i {1} {2}".format(
                    install_plugins,
                    inputs,
                    self.manager_blueprint_path)

        out = self.client_executor(
            bootstrap_command,
            fabric_env=self.centos_client_env,
            within_cfy_env=True)

        # TODO: This is really not where specific wording checks for bootstrap
        # output belong, but left in for the moment until this test can be
        # reworked as there is a lot of cruft
        self.assertIn('Bootstrap complete', out, 'Bootstrap has failed')

        self.manager_ip = self._manager_ip()
        self.client = util.create_rest_client(
            self.manager_ip,
            manager_username=self.manager_username,
            manager_password=self.manager_password
        )
        self.addCleanup(self.teardown_manager)
        self.cfy.profiles.use(
            self.manager_ip,
            manager_username=self.manager_username,
            manager_password=self.manager_password,
            manager_tenant=cli_constants.DEFAULT_TENANT_NAME
        )
        self.env._upload_plugins()

    def publish_hello_world_blueprint(self, source_archive):
        blueprint_id = 'blueprint-{0}'.format(uuid.uuid4())
        self.logger.info('Publishing hello-world example from: {0} [{1}]'
                         .format(source_archive, blueprint_id))
        self.client_executor(
            'blueprints upload {0} -n {1} -b {2}'
            .format(source_archive, self.app_blueprint_file, blueprint_id),
            fabric_env=self.centos_client_env,
            within_cfy_env=True)
        return blueprint_id

    def create_deployment(self, blueprint_id, *_):
        deployment_id = 'deployment-{0}'.format(uuid.uuid4())

        self.logger.info('Creating deployment: {0}'.format(deployment_id))
        self.client_executor(
            """deployments create {0} -b {1} -i "{2}" """
            .format(deployment_id, blueprint_id, json.dumps(
                self.deployment_inputs).replace(
                '"', "'").replace(' ', '')),
            fabric_env=self.centos_client_env,
            within_cfy_env=True)

        return deployment_id

    def install_deployment(self, deployment_id):
        self.logger.info(
            'Waiting for 15 seconds before installing deployment...')
        time.sleep(15)
        self.logger.info('Installing deployment...')
        self.client_executor(
            'executions start -d {0} install'
            .format(deployment_id),
            fabric_env=self.centos_client_env,
            within_cfy_env=True, retries=2)

    def uninstall_deployment(self):
        self.logger.info('Uninstalling deployment...')
        self.client_executor(
            'executions start -d {0} uninstall'
            .format(self.deployment_id),
            fabric_env=self.centos_client_env,
            within_cfy_env=True)

    def _test_cli_package(self):
        self.prepare_cli()
        self.install_cli()
        self.prepare_manager_blueprint()
        self.add_dns_nameservers_to_manager_blueprint(
            os.path.join(os.path.dirname(__file__),
                         '../../resources/scripts/'
                         'add_nameservers_to_subnet.py'))
        inputs = self._update_username_password_inputs(self.bootstrap_inputs)
        self.bootstrap_manager(inputs)
        blueprint_id = self.publish_hello_world_blueprint(self.helloworld_url)
        self.deployment_id = self.create_deployment(blueprint_id)
        self.addCleanup(self.uninstall_deployment)
        self.install_deployment(self.deployment_id)
        self.logger.info("Deployment {0} installed successfully! will now "
                         "make sure it actually "
                         "works".format(self.deployment_id))
        self.logger.info("deployment http endpoint is: {0}".format(
            self._get_app_property('http_endpoint')))
        self.assert_deployment_working(
            self._get_app_property('http_endpoint'))

    def _manager_ip(self):
        # Expecting a line like:
        # Requesting status from manager... [ip=192.0.2.24]
        ip = re.search(
            '\[ip='  # [ literal needs escaping
            '('  # start of match group
            '[\d.]'  # character class of digits and (literal) .
            '{7,15}'  # repeat between 7 and 15 times
            ')'  # end of match group
            '\]',  # literal ]
            self._execute_command_on_linux(
                'status',
                fabric_env=self.centos_client_env,
                within_cfy_env=True),
            ).group(1)
        self.logger.info(ip)
        return ip.split('\n')[0]

    def _get_app_property(self, property_name):
        outputs_raw = (self.client_executor(
            'deployments outputs {0}'.format(self.deployment_id),
            fabric_env=self.centos_client_env, within_cfy_env=True))
        self.logger.info(outputs_raw)

        # Expecting something like:
        # test_windows_cli_package: INFO: Retrieving outputs for deployment...
        #    - "http_endpoint":
        #        Description: Web server's external endpoint
        #        Value: http://23.23.240.143:8080'''

        # TODO: This is a really ugly patch on a bafflingly bad approach
        # It should instead be getting this through an actual API call or
        # similar, not by parsing the output, but time is very short
        result = outputs_raw.splitlines()
        result = '\n'.join(result[1:])
        result = yaml.load(result)

        result = {
            item.keys()[0]: item.values()[0]
            for item in result
        }
        return result[property_name]['Value']

    @retry(stop_max_attempt_number=3, wait_fixed=3000)
    def assert_deployment_working(self, url):
        self.logger.info('Asserting deployment deployed successfully')
        server_page_response = requests.get(url)
        self.assertEqual(200, server_page_response.status_code,
                         'Failed to get home page of app')
        self.logger.info('Example deployed successfully')

    def cleanup(self):
        self.local_env.execute('uninstall',
                               task_retries=40,
                               task_retry_interval=30)

    def teardown_manager(self):
        self.logger.info('Tearing down Cloudify manager...')
        self.client_executor(
            'teardown -f --ignore-deployments',
            within_cfy_env=True, warn_only=True)

    def go_offline(self, fabric_env):
        self._execute_command_on_linux('chmod +w /etc/resolv.conf',
                                       fabric_env,
                                       sudo=True)
        self._execute_command_on_linux('echo "" > /etc/resolv.conf',
                                       fabric_env,
                                       sudo=True)
        self.assert_offline(fabric_env)

    def get_dns(self, env=None):
        env = env or self.centos_client_env
        return self.dns(env)

    @contextmanager
    def dns(self, fabric_env, dns_name_servers=('8.8.8.8', '8.8.4.4')):
        """
        Enables setting custom dns servers on the local machine.
        This is useful mainly when the bootstrap doesn't contain a
        dns_nameservers.

        :param dns_name_servers: an iterable of dns addresses.
        defaults to ('8.8.8.8', '8.8.4.4').
        :return: None
        """
        self.client_executor(
            'chmod +w /etc/resolv.conf',
            fabric_env=fabric_env,
            sudo=True)

        self._add_dns(fabric_env, dns_name_servers)

        yield

        self._remove_dns(fabric_env, dns_name_servers)

        self.assert_offline(fabric_env)

    def _add_dns(self,
                 fabric_env=None,
                 dns_name_servers=('8.8.8.8', '8.8.4.4')):
        if not fabric_env:
            fabric_env = self.centos_client_env
        for server in dns_name_servers:
            self.logger.info('Adding {0} to dns list'.format(server))
            self.client_executor(
                "echo 'nameserver {0}' >> /etc/resolv.conf"
                .format(server),
                fabric_env=fabric_env,
                sudo=True)

    def _remove_dns(self,
                    fabric_env=None,
                    dns_name_servers=('8.8.8.8', '8.8.4.4')):
        if not fabric_env:
            fabric_env = self.centos_client_env
        for server in dns_name_servers:
            self.logger.info('Removing {0} from dns list'.format(server))
            self.client_executor(
                "sed -i '/nameserver {0}/c\\' /etc/resolv.conf"
                .format(server),
                fabric_env=fabric_env,
                sudo=True)

    def assert_offline(self, fabric_env, run_on_client=True):
        execute_command = self.client_executor
        if not run_on_client:
            execute_command = self.manager_executor

        out = execute_command(
            'ping -c 2 {0}'.format(CHECK_URL),
            fabric_env=fabric_env,
            warn_only=True)
        self.assertIn('unknown host {0}'.format(CHECK_URL), out)
        self.assertNotIn('bytes from', out)

    def install_python27(self):
        with self.get_dns():

            self.logger.info('installing python 2.7...')

            self.client_executor('yum -y update', sudo=True)
            self.client_executor(
                'yum install yum-downloadonly wget '
                'mlocate yum-utils python-devel '
                'libyaml-devel ruby rubygems '
                'ruby-devel make gcc git -y', sudo=True)
            self.client_executor(
                'yum groupinstall -y \'development '
                'tools\'', sudo=True)
            self.client_executor(
                'yum install -y zlib-devel bzip2-devel '
                'openssl-devel xz-libs', sudo=True)
            self.client_executor(
                'curl -LO http://www.python.org/ftp/python/'
                '2.7.8/Python-2.7.8.tar.xz', sudo=True)
            self.client_executor('xz -d Python-2.7.8.tar.xz', sudo=True)
            self.client_executor('tar -xvf Python-2.7.8.tar', sudo=True)
            with cd('Python-2.7.8'):
                self.client_executor('./configure --prefix=/usr', sudo=True)
                self.client_executor('make', sudo=True)
                self.client_executor('make altinstall', sudo=True)
            self.client_executor('alias python=python2.7', sudo=True)


def wait_for_connection(env_settings, executor,
                        logger=None, retries=10,
                        retry_interval=30, timeout=10,
                        start_delay=30):
    """
    Asserts that a machine received the ssh key for the key manager, and
    it is no ready to be connected via ssh.
    :param env_settings: The fabric setting for the remote machine.
    :param executor: An executer function, which executes code on the
    remote machine.
    :param logger: custom logger. defaults to None.
    :param retries: number of time to check for availability. default to
    10.
    :param retry_interval: length of the intervals between each try.
    defaults to 30.
    :param timeout: timeout for each check try. default to 60.
    :param start_delay: Time in seconds to wait before starting. Sometimes
    required due to delay in IaaS configuration of SSH on deployed guests.
    :return: None
    """
    local_env_setting = copy.deepcopy(env_settings)
    local_env_setting.update({'abort_exception': FabException})
    local_env_setting.update({'timeout': timeout})

    logger.info('Waiting for {0} seconds before checking ssh connection'
                .format(start_delay))
    time.sleep(start_delay)

    if logger:
        logger.info('Waiting for ssh key to register on the vm...')
    while retries >= 0:
        try:
            executor('echo Success', fabric_env=local_env_setting)
            if logger:
                logger.info('Machine is ready to be logged in...')
            return
        except FabException as e:
            if retries == 0:
                raise e
            else:
                if logger:
                    logger.info('Machine is not yet ready, waiting for {0}'
                                ' secs and trying again'
                                .format(retry_interval))
                retries -= 1
                time.sleep(retry_interval)
                continue
