########
# Copyright (c) 2019 Cloudify Platform Ltd. All rights reserved
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

from ipaddress import ip_address, ip_network
import textwrap

import hashlib
import json
import os
import re
import time
import uuid
import yaml
from retrying import retry
from contextlib import contextmanager
from distutils.version import LooseVersion

import retrying
from fabric import Connection

from cosmo_tester.framework import util

from cloudify_cli.constants import DEFAULT_TENANT_NAME

HEALTHY_STATE = 'OK'
REMOTE_PRIVATE_KEY_PATH = '/etc/cloudify/key.pem'
REMOTE_PUBLIC_KEY_PATH = '/etc/cloudify/public_key'
REMOTE_OPENSTACK_CONFIG_PATH = '/etc/cloudify/openstack_config.json'
SANITY_MODE_FILE_PATH = '/opt/manager/sanity_mode'

ATTRIBUTES = util.get_attributes()


class VM(object):

    def __init__(self, image_type):
        self.image_type = image_type
        self.upload_plugins = None
        self._image_name = None
        self.userdata = ""
        self.enable_ssh_wait = True
        self.should_finalize = True
        self.restservice_expected = False

    def assign(
            self,
            public_ip_address,
            private_ip_address,
            networks,
            rest_client,
            ssh_key,
            cfy,
            attributes,
            logger,
            tmpdir,
            upload_plugins,  # Ignored
            node_instance_id,
            deployment_id,
            server_id,
    ):
        self.ip_address = public_ip_address
        self.private_ip_address = private_ip_address
        self.client = rest_client
        self.deleted = False
        self._ssh_key = ssh_key
        self._cfy = cfy
        self._attributes = attributes
        self._logger = logger
        self._openstack = util.create_openstack_client()
        self._tmpdir = os.path.join(tmpdir, public_ip_address)
        self.node_instance_id = None
        self.deployment_id = None
        self.node_instance_id = node_instance_id
        self.deployment_id = deployment_id
        self.server_id = server_id

    @retrying.retry(stop_max_attempt_number=60, wait_fixed=3000)
    def wait_for_ssh(self):
        if self.enable_ssh_wait:
            with self.ssh() as conn:
                conn.run("echo SSH is up for {}".format(self.ip_address))

    @property
    def private_key_path(self):
        return self._ssh_key.private_key_path

    @property
    def linux_username(self):
        return self._linux_username or self._attributes.default_linux_username

    @linux_username.setter
    def linux_username(self, user):
        self._linux_username = user

    @contextmanager
    def ssh(self):
        conn = Connection(
            host=self.ip_address,
            user=self.linux_username,
            connect_kwargs={
                'key_filename': self.private_key_path,
            },
            port=22,
            connect_timeout=3,
        )
        try:
            conn.open()
            yield conn
        finally:
            conn.close()

    def __str__(self):
        return 'Cloudify Test VM ({image}) [{ip}]'.format(
            image=self.image_name,
            ip=self.ip_address,
        )

    def stop(self):
        """Deletes this instance from the OpenStack envrionment."""
        self._logger.info('Stopping server.. [id=%s]', self.server_id)
        self._openstack.compute.stop_server(self.server_id)
        self._wait_for_server_to_be_stopped()
        self.stopped = True

    def finalize_preparation(self):
        """Complete preparations for using a new instance."""
        self.wait_for_ssh()
        if self.restservice_expected:
            self.use()
            self.wait_for_manager()
        self.upload_necessary_files()

    @retrying.retry(stop_max_attempt_number=12, wait_fixed=5000)
    def _wait_for_server_to_be_stopped(self):
        self._logger.info('Waiting for server to stop...')
        servers = [x for x in self._openstack.compute.servers()
                   if x.id == self.server_id
                   and x.status != 'SHUTOFF']
        if servers:
            self._logger.info('- server.status = %s', servers[0].status)
        assert len(servers) == 0
        self._logger.info('Server stopped!')

    def verify_services_are_running(self):
        return True

    def use(self, tenant=None):
        return True

    def wait_for_manager(self):
        return True

    def upload_plugin(self, plugin_name, tenant_name=DEFAULT_TENANT_NAME):
        return True

    def upload_necessary_files(self):
        return True

    @property
    def ssh_key(self):
        return self._ssh_key

    def get_remote_file(self, remote_path, local_path):
        """ Dump the contents of the remote file into the local path """
        # Similar to the way fabric1 did it
        remote_tmp = '/tmp/' + hashlib.sha1(remote_path).hexdigest()
        self.run_command(
            'cp {} {}'.format(remote_path, remote_tmp),
            use_sudo=True,
        ),

        with self.ssh() as fabric_ssh:
            fabric_ssh.get(
                remote_tmp,
                local_path,
            )

    def put_remote_file(self, remote_path, local_path):
        """ Dump the contents of the local file into the remote path """

        with self.ssh() as fabric_ssh:
            # Similar to the way fabric1 did it
            remote_tmp = '/tmp/' + hashlib.sha1(remote_path).hexdigest()
            fabric_ssh.put(
                local_path,
                remote_tmp,
            )
        self.run_command(
            'mkdir -p {}'.format(
                os.path.dirname(remote_path),
            ),
            use_sudo=True,
        )
        self.run_command(
            'mv {} {}'.format(remote_tmp, remote_path),
            use_sudo=True,
        )

    def get_remote_file_content(self, remote_path):
        tmp_local_path = os.path.join(self._tmpdir, str(uuid.uuid4()))

        try:
            self.get_remote_file(remote_path, tmp_local_path)
            with open(tmp_local_path, 'r') as f:
                content = f.read()
        finally:
            if os.path.exists(tmp_local_path):
                os.unlink(tmp_local_path)
        return content

    def put_remote_file_content(self, remote_path, content):
        tmp_local_path = os.path.join(self._tmpdir, str(uuid.uuid4()))

        try:
            with open(tmp_local_path, 'w') as f:
                f.write(content)

            self.put_remote_file(remote_path, tmp_local_path)

        finally:
            if os.path.exists(tmp_local_path):
                os.unlink(tmp_local_path)

    def run_command(self, command, use_sudo=False, warn_only=False):
        with self.ssh() as fabric_ssh:
            if use_sudo:
                return fabric_ssh.sudo(command, warn=warn_only)
            else:
                return fabric_ssh.run(command, warn=warn_only)

    def get_node_id(self):
        node_id_parts = self.run_command('cfy_manager node get-id').split(': ')
        if len(node_id_parts) < 2:
            raise RuntimeError('Status reporter is not installed')
        return node_id_parts[1]

    _linux_username = None
    image_name = ATTRIBUTES['default_linux_image_name']
    username = ATTRIBUTES['default_linux_username']
    image_type = 'centos'


class _CloudifyManager(VM):

    def assign(
            self,
            public_ip_address,
            private_ip_address,
            networks,
            rest_client,
            ssh_key,
            cfy,
            attributes,
            logger,
            tmpdir,
            upload_plugins,
            node_instance_id,
            deployment_id,
            server_id,
    ):
        self.ip_address = public_ip_address
        self.private_ip_address = private_ip_address
        self.client = rest_client
        self.deleted = False
        self.networks = networks
        self._ssh_key = ssh_key
        self._cfy = cfy
        self._attributes = attributes
        self._logger = logger
        self._tmpdir = os.path.join(tmpdir, str(uuid.uuid4()))
        os.makedirs(self._tmpdir)
        self._openstack = util.create_openstack_client()
        self.additional_install_config = {}
        # Only set this if it wasn't explicitly set elsewhere.
        # (otherwise multiple test managers cannot have different settings for
        # this value due to the way we deploy them)
        if self.upload_plugins is None:
            self.upload_plugins = upload_plugins
        self.node_instance_id = node_instance_id
        self.deployment_id = deployment_id
        self.server_id = server_id

    def upload_necessary_files(self):
        self._logger.info('Uploading necessary files to %s', self)
        openstack_config_file = self._create_openstack_config_file()

        self.put_remote_file(REMOTE_OPENSTACK_CONFIG_PATH,
                             openstack_config_file)

        self.put_remote_file(REMOTE_PRIVATE_KEY_PATH,
                             self._ssh_key.private_key_path)
        self.put_remote_file(REMOTE_PUBLIC_KEY_PATH,
                             self._ssh_key.public_key_path)

        with self.ssh() as fabric_ssh:
            fabric_ssh.sudo('chown cfyuser:cfyuser {key_file}'.format(
                key_file=REMOTE_PRIVATE_KEY_PATH,
            ))
            fabric_ssh.sudo('chown cfyuser:cfyuser {key_file}'.format(
                key_file=REMOTE_PRIVATE_KEY_PATH,
            ))

            fabric_ssh.sudo('chmod 400 {key_file}'.format(
                key_file=REMOTE_PRIVATE_KEY_PATH,
            ))
            fabric_ssh.sudo('chmod 440 {key_file}'.format(
                key_file=REMOTE_PUBLIC_KEY_PATH,
            ))

            self.enter_sanity_mode()

    def enter_sanity_mode(self):
        """
        Test Managers should be in sanity mode to skip Cloudify license
        validations.
        """
        self.put_remote_file_content(SANITY_MODE_FILE_PATH, 'sanity')
        with self.ssh() as fabric_ssh:
            fabric_ssh.sudo('chown cfyuser:cfyuser {sanity_mode}'.format(
                sanity_mode=SANITY_MODE_FILE_PATH,
            ))
            fabric_ssh.sudo('chmod 440 {sanity_mode}'.format(
                sanity_mode=SANITY_MODE_FILE_PATH,
            ))

    def upload_plugin(self, plugin_name, tenant_name=DEFAULT_TENANT_NAME):
        # Included in VM so that bootstrapped managers can use it
        all_plugins = util.get_plugin_wagon_urls()
        plugins = [p for p in all_plugins if p['name'] == plugin_name]
        if len(plugins) != 1:
            self._logger.error(
                '%s plugin wagon not found in:%s%s',
                plugin_name,
                os.linesep,
                json.dumps(all_plugins, indent=2))
            raise RuntimeError(
                '{} plugin not found in wagons list'.format(plugin_name))
        plugin = plugins[0]
        self._logger.info('Uploading %s plugin [%s] to %s..',
                          plugin_name,
                          plugin['wgn_url'],
                          self)

        yaml_snippet = '--yaml-path {0}'.format(
            plugin['plugin_yaml_url'])
        try:
            with self.ssh() as fabric_ssh:
                # This will only work for images as cfy is pre-installed there.

                # from some reason this method is usually less error prone.
                fabric_ssh.run(
                    'cfy plugins upload {0} -t {1} {2}'.format(
                        plugin['wgn_url'], tenant_name, yaml_snippet
                    ))
        except Exception:
            self.use()
            command = [plugin['wgn_url'], '-t', tenant_name]
            if yaml_snippet:
                command += ['--yaml-path', plugin['plugin_yaml_url']]
            self._cfy.plugins.upload(command)

        self.wait_for_all_executions()

    @property
    def remote_private_key_path(self):
        """Returns the private key path on the manager."""
        return REMOTE_PRIVATE_KEY_PATH

    @property
    def remote_public_key_path(self):
        """Returns the public key path on the manager."""
        return REMOTE_PUBLIC_KEY_PATH

    def __str__(self):
        return 'Cloudify manager [{}]'.format(self.ip_address)

    @retrying.retry(stop_max_attempt_number=3, wait_fixed=3000)
    def use(self, tenant=None, profile_name=None, cert_path=None):
        kwargs = {}
        if profile_name is not None:
            kwargs['profile_name'] = profile_name
        if cert_path:
            kwargs['rest_certificate'] = cert_path
        self._cfy.profiles.use([
            self.ip_address,
            '-u', self._attributes.cloudify_username,
            '-p', self._attributes.cloudify_password,
            '-t', tenant or self._attributes.cloudify_tenant,
        ], **kwargs)

    def verify_services_are_running(self):
        if self.image_type.startswith('4'):
            return self._old_verify_services_are_running()
        else:
            return self._new_verify_services_are_running()

    @retrying.retry(stop_max_attempt_number=6 * 10, wait_fixed=10000)
    def _new_verify_services_are_running(self):
        with self.ssh() as fabric_ssh:
            # the manager-ip-setter script creates the `touched` file when it
            # is done.
            try:
                # will fail on bootstrap based managers
                fabric_ssh.run('systemctl | grep manager-ip-setter')
            except Exception:
                pass
            else:
                self._logger.info('Verify manager-ip-setter is done..')
                fabric_ssh.run('cat /opt/cloudify/manager-ip-setter/touched')

        self._logger.info(
            'Verifying all services are running on manager %s...',
            self.ip_address,
        )

        manager_status = self.client.manager.get_status()
        if manager_status['status'] == HEALTHY_STATE:
            return

        for display_name, service in manager_status['services'].items():
            assert service['status'] == 'Active', \
                'service {0} is in {1} state'.format(
                    display_name, service['status'])

    @retrying.retry(stop_max_attempt_number=6 * 10, wait_fixed=10000)
    def _old_verify_services_are_running(self):
        with self.ssh() as fabric_ssh:
            # the manager-ip-setter script creates the `touched` file when it
            # is done.
            try:
                # will fail on bootstrap based managers
                fabric_ssh.run('systemctl | grep manager-ip-setter')
            except Exception:
                pass
            else:
                self._logger.info('Verify manager-ip-setter is done..')
                fabric_ssh.run('cat /opt/cloudify/manager-ip-setter/touched')

        self._logger.info(
            'Verifying all services are running on manager %s...',
            self.ip_address,
        )
        status = self.client.manager.get_status()
        for service in status['services']:
            for instance in service['instances']:
                if all(service not in instance['Id'] for
                       service in ['postgresql', 'rabbitmq']):
                    assert instance['SubState'] == 'running', \
                        'service {0} is in {1} state'.format(
                            service['display_name'], instance['SubState'])

    @property
    def image_name(self):
        if self._image_name is None:
            if self.image_type == 'master':
                self._image_name = get_latest_manager_image_name()
            else:
                self._image_name = ATTRIBUTES[
                    'cloudify_manager_{}_image_name'.format(
                        self.image_type.replace('.', '_')
                    )
                ]
                if ATTRIBUTES['default_manager_distro'] == 'rhel':
                    self._image_name += '-rhel'

        return self._image_name

    @property
    def api_version(self):
        if self.image_type == '4.3.1':
            return 'v3'
        else:
            return 'v3.1'

    # passed to cfy. To be overridden in pre-4.0 versions
    restore_tenant_name = None
    tenant_name = 'default_tenant'

    def teardown(self):
        with self.ssh() as fabric_ssh:
            fabric_ssh.run('cfy_manager remove --force')
            fabric_ssh.sudo('yum remove -y cloudify-manager-install')

    def _create_config_file(self, upload_license=True):
        config_file = self._tmpdir / 'config_{0}.yaml'.format(self.ip_address)
        cloudify_license_path = \
            '/tmp/test_valid_paying_license.yaml' if upload_license else ''
        install_config = {
            'manager': {
                'public_ip': str(self.ip_address),
                'private_ip': str(self.private_ip_address),
                'hostname': str(self.server_id),
                'security': {
                    'admin_username': self._attributes.cloudify_username,
                    'admin_password': self._attributes.cloudify_password,
                },
                'cloudify_license_path': cloudify_license_path,
            },
        }

        # Add any additional bootstrap inputs passed from the test
        install_config.update(self.additional_install_config)
        install_config_str = yaml.dump(install_config)

        self._logger.info(
            'Install config:\n%s', str(install_config_str))
        config_file.write_text(install_config_str)
        return config_file

    def bootstrap(self, enter_sanity_mode=True, upload_license=False,
                  blocking=True, restservice_expected=True):
        self.restservice_expected = restservice_expected
        manager_install_rpm = \
            ATTRIBUTES.cloudify_manager_install_rpm_url.strip() or \
            util.get_manager_install_rpm_url()

        install_config = self._create_config_file(
            upload_license and not util.is_community())
        install_rpm_file = 'cloudify-manager-install.rpm'
        with self.ssh() as fabric_ssh:
            fabric_ssh.run('mkdir -p /tmp/bs_logs')
            self.put_remote_file(
                '/tmp/cloudify.conf',
                install_config,
            )
            if upload_license:
                self.put_remote_file(
                    '/tmp/test_valid_paying_license.yaml',
                    util.get_resource_path('test_valid_paying_license.yaml'),
                )

            commands = [
                'echo "Downloading RPM..." >/tmp/bs_logs/1_download',
                (
                    'curl -S {0} -o {1} --silent --write-out "'
                    'Response code: %{{response_code}}\n'
                    'Downloaded bytes: %{{size_download}}\n'
                    'Download duration: %{{time_total}}\n'
                    'Speed bytes/second: %{{speed_download}}\n'
                    '" 2>&1 >>/tmp/bs_logs/1_download'.format(
                        manager_install_rpm,
                        install_rpm_file,
                    )
                ),
                'sudo yum install -y {0} > /tmp/bs_logs/2_yum 2>&1'.format(
                    install_rpm_file,
                ),
                'sudo mv /tmp/cloudify.conf /etc/cloudify/config.yaml',
                'cfy_manager install > /tmp/bs_logs/3_install 2>&1',
                'touch /tmp/bootstrap_complete'
            ]

            install_command = ' && '.join(commands)
            install_command = (
                '( ' + install_command + ') '
                '|| touch /tmp/bootstrap_failed &'
            )

            install_file = self._tmpdir / 'install_{0}.yaml'.format(
                self.ip_address,
            )
            install_file.write_text(install_command)
            self.put_remote_file('/tmp/bootstrap_script', install_file)

            fabric_ssh.run('nohup bash /tmp/bootstrap_script')

        if blocking:
            while True:
                if self.bootstrap_is_complete():
                    break
                else:
                    time.sleep(5)
            if enter_sanity_mode:
                self.enter_sanity_mode()
            self.finalize_preparation()

    def bootstrap_is_complete(self):
        with self.ssh() as fabric_ssh:
            # Using a bash construct because fabric seems to change its mind
            # about how non-zero exit codes should be handled frequently
            result = fabric_ssh.run(
                'if [[ -f /tmp/bootstrap_complete ]]; then'
                '  echo done; '
                'elif [[ -f /tmp/bootstrap_failed ]]; then '
                '  echo failed; '
                'else '
                '  echo not done; '
                'fi'
            ).stdout.strip()

            if result == 'done':
                self._logger.info('Bootstrap complete.')
                self.finalize_preparation()
                return True
            else:
                # To aid in troubleshooting (e.g. where a VM runs commands too
                # slowly)
                fabric_ssh.run('date > /tmp/cfy_mgr_last_check_time')
                if result == 'failed':
                    self._logger.error('BOOTSTRAP FAILED!')
                    # Get all the logs on failure
                    fabric_ssh.run(
                        'cat /tmp/bs_logs/*'
                    )
                    raise RuntimeError('Bootstrap failed.')
                else:
                    fabric_ssh.run(
                        'tail -n5 /tmp/bs_logs/* || echo Waiting for logs'
                    )
                    self._logger.info('Bootstrap in progress...')
                    return False

    def _create_openstack_config_file(self):
        openstack_config_file = self._tmpdir / 'openstack_config.json'
        openstack_config_file.write_text(json.dumps(
            util.get_openstack_config(), indent=2))
        return openstack_config_file

    @retrying.retry(stop_max_attempt_number=200, wait_fixed=1000)
    def wait_for_all_executions(self, include_system_workflows=True):
        executions = self.client.executions.list(
            include_system_workflows=include_system_workflows,
            _all_tenants=True,
            _get_all_results=True
        )
        for execution in executions:
            if execution['status'] != 'terminated':
                raise StandardError(
                    'Timed out: An execution did not terminate'
                )

    def wait_for_manager(self):
        if self.image_type.startswith('4'):
            return self._old_wait_for_manager()
        else:
            return self._new_wait_for_manager()

    @retrying.retry(stop_max_attempt_number=60, wait_fixed=1000)
    def _new_wait_for_manager(self):
        manager_status = self.client.manager.get_status()
        if manager_status['status'] != HEALTHY_STATE:
            raise StandardError(
                'Timed out: Reboot did not complete successfully'
            )

    @retrying.retry(stop_max_attempt_number=60, wait_fixed=1000)
    def _old_wait_for_manager(self):
        status = self.client.manager.get_status()
        for service in status['services']:
            for instance in service['instances']:
                if any(service not in instance['Id'] for
                       service in ['postgresql', 'rabbitmq']):
                    if instance['state'] != 'running':
                        raise StandardError(
                            'Timed out: Reboot did not complete successfully'
                        )

    def enable_nics(self):
        """
        Extra network interfaces need to be manually enabled on the manager
        `manager.networks` is a dict that looks like this:
        {
            "network_0": "10.0.0.6",
            "network_1": "11.0.0.6",
            "network_2": "12.0.0.6"
        }
        """
        # The MTU is set to 1450 because we're using a static BOOTPROTO here
        # (as opposed to DHCP), which sets a lower default by default
        template = textwrap.dedent("""
            DEVICE="eth{0}"
            BOOTPROTO="static"
            ONBOOT="yes"
            TYPE="Ethernet"
            USERCTL="yes"
            PEERDNS="yes"
            IPV6INIT="no"
            PERSISTENT_DHCLIENT="1"
            IPADDR="{1}"
            NETMASK="255.255.255.128"
            DEFROUTE="no"
            MTU=1450
        """)

        self._logger.info('Adding extra NICs...')

        # Need to do this for each network except 0 (eth0 is already enabled)
        for i in range(1, len(self.networks)):
            network_file_path = self._tmpdir / 'network_cfg_{0}'.format(i)
            ip_addr = self.networks['network_{0}'.format(i)]
            config_content = template.format(i, ip_addr)

            # Create and copy the interface config
            network_file_path.write_text(config_content)
            with self.ssh() as fabric_ssh:
                self.put_remote_file(
                    '/etc/sysconfig/network-scripts/ifcfg-eth{0}'.format(i),
                    network_file_path,
                )
                # Start the interface
                fabric_ssh.sudo('ifup eth{0}'.format(i))


def get_latest_manager_image_name():
    """
    Returns the manager image name based on installed CLI version.
    For CLI version "4.0.0-m15"
    Returns: "cloudify-manager-premium-4.0m15"
    """
    specific_manager_name = ATTRIBUTES.cloudify_manager_latest_image.strip()

    if specific_manager_name:
        image_name = specific_manager_name
    else:
        version = util.get_cli_version()
        version_num, _, version_milestone = version.partition('-')

        # starting 5.0.0, we name images with the trailing .0
        if LooseVersion(version_num) < '5.0.0':
            if version_num.endswith('.0') and version_num.count('.') > 1:
                version_num = version_num[:-2]

        distro = ATTRIBUTES.default_manager_distro
        version = version_num + version_milestone
        image_name = '{prefix}-{suffix}'.format(
            prefix=ATTRIBUTES.cloudify_manager_image_name_prefix,
            suffix=version
        )

        if distro != 'centos':
            image_name = image_name + '-{distro}'.format(distro=distro)

    return image_name


def get_image(version):
    supported = [
        '4.3.1', '4.4', '4.5', '4.5.5', '4.6', '5.0.5', 'master',
        'centos',
    ]
    if version not in supported:
        raise ValueError(
            '{ver} is not a supported image. Supported: {supported}'.format(
                ver=version,
                supported=','.join(supported),
            )
        )

    if version == 'centos':
        img_cls = VM
    else:
        img_cls = _CloudifyManager

    return img_cls(version)


class TestHosts(object):

    def __init__(self,
                 cfy,
                 ssh_key,
                 tmpdir,
                 attributes,
                 logger,
                 number_of_instances=1,
                 instances=None,
                 upload_plugins=True,
                 request=None,
                 flavor=None,
                 multi_net=False,
                 bootstrappable=False):
        """
        instances: supply a list of VM instances.
        This allows pre-configuration to happen before starting the hosts, or
        for a list of instances of different versions to be created at once.
        if instances is provided, number_of_instances will be ignored
        """

        super(TestHosts, self).__init__()
        self._logger = logger
        self._attributes = attributes
        self._tmpdir = tmpdir
        self._ssh_key = ssh_key
        self._cfy = cfy
        self.preconfigure_callback = None
        if instances is None:
            self.instances = [
                get_image('master')
                for _ in range(number_of_instances)]
        else:
            self.instances = instances
        self._request = request
        self.upload_plugins = upload_plugins
        self.tenant = None
        self.deployments = []
        self.blueprints = []
        self.multi_net = multi_net
        if flavor:
            self.server_flavor = flavor
        else:
            self.server_flavor = self._attributes.manager_server_flavor_name

        if bootstrappable:
            for instance in self.instances:
                instance._image_name = ATTRIBUTES['default_linux_image_name']
                instance.should_finalize = False

    def create(self):
        """Creates the infrastructure for a Cloudify manager."""
        self._logger.info('Creating image based cloudify instances: '
                          '[number_of_instances=%d]', len(self.instances))

        test_identifier = '{test}_{time}'.format(
            # Strip out any characters from the test name that might cause
            # systems with restricted naming to become upset
            test=re.sub(
                '[^a-zA-Z0-9]',
                '',
                # This is set by pytest and looks like:
                # cosmo_tester/test_suites/image_based_tests/\
                # hello_world_test.py::test_hello_world[centos_7]
                os.environ['PYTEST_CURRENT_TEST'].split('/')[-1],
            ),
            time=int(time.time()),
        )

        image_id_instance_mapping = {}
        for instance in self.instances:
            image_id_instance_mapping[instance.image_name] = (
                image_id_instance_mapping.get(instance.image_name, [])
                + [instance]
            )

        # Connect to the infrastructure manager for setting up the tests
        self._cfy.profiles.use(
            "--manager-username", "admin",
            "--manager-password", ATTRIBUTES["manager_admin_password"],
            "--manager-tenant", "default_tenant",
            ATTRIBUTES["manager_address"],
        )

        try:
            self._logger.info('Creating test tenant')
            self._cfy.tenants.create(test_identifier)
            self.tenant = test_identifier
            self._logger.info('Using test tenant')
            self._cfy.profiles.set(
                "--manager-tenant", test_identifier,
            )

            self._upload_secrets_to_infrastructure_manager()
            self._upload_plugins_to_infrastructure_manager()
            self._upload_blueprints_to_infrastructure_manager()

            self._deploy_test_infrastructure(test_identifier)

            # Deploy hosts
            for image_id, instances in image_id_instance_mapping.items():
                self._deploy_test_vms(image_id, instances, test_identifier)

            for instance in self.instances:
                if instance.should_finalize:
                    instance.finalize_preparation()
        except Exception as err:
            self._logger.error(
                "Encountered exception trying to create test resources: %s.\n"
                "Attempting to tear down test resources.", str(err)
            )
            self.destroy()
            raise err

    def destroy(self):
        """Destroys the infrastructure. """
        try:
            self._save_manager_logs()
        except Exception as e:
            self._logger.info(
                "Unable to save logs due to exception: %s", str(e))
        finally:
            self._logger.info('Destroying test hosts..')
            if self.tenant:
                self._logger.info(
                    'Switching profile to %s on %s',
                    self.tenant,
                    ATTRIBUTES['manager_address'],
                )
                self._cfy.profiles.use(
                    ATTRIBUTES["manager_address"],
                )
                self._cfy.profiles.set('--manager-tenant', self.tenant)

                self._logger.info('Ensuring executions are stopped.')
                execs = json.loads(self._cfy.executions.list('--json').stdout)
                for execution in execs:
                    if execution['workflow_id'] != (
                        'create_deployment_environment'
                    ):
                        self._logger.info(
                            'Ensuring %s (%s) is not running.',
                            execution['id'],
                            execution['workflow_id'],
                        )
                        self._cfy.executions.cancel(
                            '--force', '--kill', execution['id'],
                        )
                    else:
                        self._logger.info(
                            'Skipping %s (%s).',
                            execution['id'],
                            execution['workflow_id'],
                        )

                # Remove tenants in the opposite order to the order they were
                # deployed in, so that we don't try to remove the
                # infrastructure before removing the VMs using it.
                self._logger.info('Uninstalling and removing deployments.')
                for deployment in reversed(self.deployments):
                    self._logger.info('Uninstalling %s', deployment)
                    self._cfy.executions.start(
                        "--deployment-id", deployment,
                        "uninstall",
                    )
                    self._logger.info('Deleting %s', deployment)
                    self._cfy.deployments.delete(deployment)

                self._logger.info('Deleting blueprints.')
                for blueprint in self.blueprints:
                    self._logger.info('Deleting %s', blueprint)
                    self._cfy.blueprints.delete(blueprint)

                self._logger.info('Deleting plugins.')
                plugins = json.loads(self._cfy.plugins.list('--json').stdout)
                for plugin in plugins:
                    if plugin["tenant_name"] != self.tenant:
                        self._logger.info(
                            'Skipping shared %s (%s)',
                            plugin['package_name'],
                            plugin['id'],
                        )
                    else:
                        self._logger.info(
                            'Deleting %s (%s)',
                            plugin['package_name'],
                            plugin['id'],
                        )
                        self._cfy.plugins.delete(plugin['id'])

                self._logger.info('Switching back to default tenant.')
                self._cfy.profiles.set('--manager-tenant', 'default_tenant')
                self._logger.info('Deleting tenant %s', self.tenant)
                self._cfy.tenants.delete(self.tenant)
                self.tenant = None

    def _upload_secrets_to_infrastructure_manager(self):
        # Used to maintain compatibility with current test framework config
        secrets_from_env = {
            "keystone_password": os.environ["OS_PASSWORD"],
            "keystone_tenant_name": (
                os.environ.get("OS_TENANT_NAME")
                or os.environ['OS_PROJECT_NAME']
            ),
            "keystone_url": os.environ["OS_AUTH_URL"],
            "keystone_username": os.environ["OS_USERNAME"],
            "region": os.environ.get("OS_REGION_NAME", "RegionOne"),
        }
        self._logger.info(
            'Uploading openstack secrets to infrastructure manager.'
        )
        for secret in [
            "keystone_password",
            "keystone_tenant_name",
            "keystone_url",
            "keystone_username",
            "region",
        ]:
            self._cfy.secrets.create(
                "--secret-string", secrets_from_env[secret],
                secret,
            )
        self._cfy.secrets.create(
            "--secret-file", self._ssh_key.public_key_path,
            "ssh_public_key",
        )

    def _upload_plugins_to_infrastructure_manager(self):
        current_plugins = json.loads(self._cfy.plugins.list('--json').stdout)
        if any(
            plugin["package_name"] == "cloudify-openstack-plugin"
            for plugin in current_plugins
        ):
            self._logger.info('Openstack plugin already present.')
        else:
            self._logger.info(
                'Uploading openstack plugin to infrastructure manager.'
            )
            self._cfy.plugins.upload(
                "--yaml-path", ATTRIBUTES['openstack_plugin_yaml_path'],
                ATTRIBUTES['openstack_plugin_path'],
            )

    def _upload_blueprints_to_infrastructure_manager(self):
        self._logger.info(
            'Uploading test blueprints to infrastructure manager.'
        )
        suffix = '-multi-net' if self.multi_net else ""
        self._cfy.blueprints.upload(
            "--blueprint-id", "infrastructure",
            util.get_resource_path(
                'infrastructure_blueprints/infrastructure{}.yaml'.format(
                    suffix,
                )
            ),
        )
        self.blueprints.append('infrastructure')
        self._cfy.blueprints.upload(
            "--blueprint-id", "test_vm",
            util.get_resource_path(
                'infrastructure_blueprints/vm{}.yaml'.format(
                    suffix,
                )
            ),
        )
        self.blueprints.append('test_vm')

    def _deploy_test_infrastructure(self, test_identifier):
        self._logger.info('Creating test infrastructure inputs.')
        infrastructure_inputs = {
            'test_infrastructure_name': test_identifier,
            'floating_network_id': ATTRIBUTES['floating_network_id'],
        }
        infrastructure_inputs_path = self._tmpdir / 'infra_inputs.yaml'
        with open(infrastructure_inputs_path, 'w') as inp_handle:
            inp_handle.write(json.dumps(infrastructure_inputs))

        self._logger.info(
            'Creating test infrastructure using infrastructure manager.'
        )
        self._cfy.deployments.create(
            "--blueprint-id", "infrastructure",
            "--inputs", infrastructure_inputs_path,
            "infrastructure"
        )
        self.deployments.append('infrastructure')
        self._cfy.executions.start(
            "--deployment-id", "infrastructure",
            "install",
        )

        self._logger.info(
            'Retrieving infrastructure details for attributes.'
        )
        infra_keypair = self._get_node_instances(
            'test_keypair', 'infrastructure',
        )[0]
        self._attributes['keypair_name'] = infra_keypair[
            'runtime_properties']['id']
        infra_network = self._get_node_instances(
            'test_network_1', 'infrastructure',
        )[0]
        self._attributes['network_name'] = infra_network[
            'runtime_properties']['name']
        infra_subnet = self._get_node_instances(
            'test_subnet_1', 'infrastructure',
        )[0]
        self._attributes['subnet_name'] = infra_subnet[
            'runtime_properties']['name']
        infra_security_group = self._get_node_instances(
            'test_security_group', 'infrastructure',
        )[0]
        self._attributes['security_group_name'] = infra_security_group[
            'runtime_properties']['name']
        if self.multi_net:
            network_names = {}
            for net in range(1, 4):
                net_details = self._get_node_instances(
                    'test_network_{}'.format(net), 'infrastructure'
                )[0]['runtime_properties']
                network_names['network_{}'.format(net - 1)] = net_details[
                    'name']
            self._attributes.network_names = network_names

            network_mappings = {}
            for sn in range(1, 4):
                subnet_details = self._get_node(
                    'test_subnet_{}'.format(sn), 'infrastructure',
                )['properties']['resource_config']
                network_mappings['network_{}'.format(sn - 1)] = ip_network(
                    # Has to be unicode for ipaddress library.
                    # Converting like this for py3 compat
                    u'{}'.format(subnet_details['cidr']),
                )
            self.network_mappings = network_mappings

    def _deploy_test_vms(self, image_id, instances, test_identifier):
        self._logger.info(
            'Preparing to deploy %d instance of image %s',
            len(instances),
            image_id,
        )

        scale_count = max(len(instances) - 1, 0)

        vm_id = 'vm_{}'.format(
            image_id
            .replace(' ', '_')
            .replace('(', '_')
            .replace(')', '_')
        )

        self._logger.info('Creating test VM inputs for %s', image_id)
        vm_inputs = {
            'test_infrastructure_name': test_identifier,
            'floating_network_id': ATTRIBUTES['floating_network_id'],
            'image': image_id,
            'flavor': self.server_flavor,
            'userdata': instances[0].userdata,
        }
        vm_inputs_path = self._tmpdir / '{}.yaml'.format(vm_id)
        with open(vm_inputs_path, 'w') as inp_handle:
            inp_handle.write(json.dumps(vm_inputs))

        self._logger.info('Deploying instance of %s', image_id)
        self._cfy.deployments.create(
            "--blueprint-id", "test_vm",
            "--inputs", vm_inputs_path,
            vm_id,
        )
        self.deployments.append(vm_id)
        self._cfy.executions.start(
            "--deployment-id", vm_id,
            "install",
        )

        if scale_count:
            self._logger.info(
                'Deploying %d more instances of %s',
                scale_count,
                image_id,
            )
            self._cfy.executions.start(
                "--deployment-id", vm_id,
                "--parameters", "scalable_entity_name=vmgroup",
                "--parameters", "delta={}".format(scale_count),
                "scale",
            )

        self._logger.info('Retrieving deployed instance details.')
        node_instances = self._get_node_instances('test_host', vm_id)
        if len(node_instances) != len(instances):
            raise AssertionError(
                "Unexpected node instance count- found {found}/{expected}"
                .format(
                    found=len(node_instances),
                    expected=len(instances),
                )
            )

        self._logger.info('Storing instance details.')
        for idx in range(len(instances)):
            self._update_instance(
                instances[idx],
                node_instances[idx]
            )

    def _get_node_instances(self, node_name, deployment_id):
        node_instances = []

        node_instance_list = json.loads(self._cfy(
            "node-instances", "list", "--json",
            "--deployment-id", deployment_id,
        ).stdout)

        for inst in node_instance_list:
            if inst['node_id'] == node_name:
                node_instances.append(json.loads(self._cfy(
                    "node-instances", "get", "--json",
                    inst['id'],
                ).stdout))

        return node_instances

    def _get_node(self, node_name, deployment_id):
        return json.loads(self._cfy(
            "nodes", "get", "--json",
            "--deployment-id", deployment_id,
            node_name,
        ).stdout)

    def _update_instance(self, instance, node_instance):
        runtime_props = node_instance['runtime_properties']

        public_ip_address = runtime_props['public_ip_address']
        private_ip_address = runtime_props['ip']

        node_instance_id = node_instance['id']
        deployment_id = node_instance['deployment_id']
        server_id = runtime_props['id']

        networks = {}
        if self.multi_net:
            # Filter out public IPs from ipv4 addresses
            ipv4_addresses = sorted([
                # Has to be unicode for ipaddress library.
                # Converting like this for py3 compat
                ip_address(u'{}'.format(addr))
                for addr in runtime_props['ipv4_addresses']
            ])

            for ip in ipv4_addresses:
                for net_name, network in self.network_mappings.items():
                    if ip in network:
                        networks[net_name] = str(ip)
                        break

        if hasattr(instance, 'api_version'):
            rest_client = util.create_rest_client(
                public_ip_address,
                username=self._attributes.cloudify_username,
                password=self._attributes.cloudify_password,
                tenant=self._attributes.cloudify_tenant,
                api_version=instance.api_version,
            )
        else:
            rest_client = None
        instance.assign(
            public_ip_address,
            private_ip_address,
            networks,
            rest_client,
            self._ssh_key,
            self._cfy,
            self._attributes,
            self._logger,
            self._tmpdir,
            self.upload_plugins,
            node_instance_id,
            deployment_id,
            server_id,
        )

    def _save_manager_logs(self):
        self._logger.debug('_save_manager_logs started')
        logs_dir = os.environ.get('CFY_LOGS_PATH_LOCAL')
        test_path = self._tmpdir.name
        if not logs_dir:
            self._logger.debug('CFY_LOGS_PATH_LOCAL has not been set, not '
                               'saving the logs.')
            return

        self._logger.info(
            'Attempting to save manager logs for test:  {0}'.format(test_path))
        logs_dir = os.path.join(os.path.expanduser(logs_dir), test_path)
        util.mkdirs(logs_dir)
        for i, instance in enumerate(self.instances):
            instance_deleted = getattr(instance, "deleted", None)
            if instance_deleted:
                self._logger.info('Cannot save logs for server with index '
                                  '%d, since server has been deleted or not '
                                  'initialized.', i)
            else:
                self._save_logs_for_instance(instance, logs_dir, i)

        self._logger.debug('_save_manager_logs completed')

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def _save_logs_for_instance(self, instance, logs_dir, instance_index):
        def _generate_prefix():
            """
            :return: log tar file prefix in the following format:
                <instance_class_name>__[<pytest_params_if_exist>__] +
                    + <index_number_in_instances_list>__<server_id>__
            """
            prefix = '{}__'.format(instance.__class__.__name__)
            if self._request and hasattr(self._request, 'param'):
                prefix += '{}__'.format(self._request.param)
            prefix += 'index_{}__'.format(instance_index)
            return prefix

        self._logger.info('Attempting to download logs for Cloudify Manager '
                          'with ID: %s...', instance.server_id)
        self._logger.info('Switching profiles...')
        try:
            instance.use()
            logs_filename = '{}__{}_logs.tar.gz'.format(_generate_prefix(),
                                                        instance.server_id)
            target = os.path.join(logs_dir, logs_filename)
            self._logger.info('Force updating the profile...')
            self._cfy.profiles.set(
                ssh_key=instance.ssh_key.private_key_path,
                ssh_user=instance.username,
                skip_credentials_validation=True)
            self._logger.info('Starting to download the logs...')
            self._cfy.logs.download(output_path=target)
            self._logger.info('Purging the logs...')
            self._cfy.logs.purge(force=True)
        except Exception as err:
            self._logger.warning(
                'Failed to download logs for node with ID %(id)s, due to '
                'error: %(err)s',
                {
                    'id': instance.server_id,
                    'err': str(err),
                },
            )
