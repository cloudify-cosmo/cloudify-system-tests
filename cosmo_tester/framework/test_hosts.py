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

import textwrap
from abc import (
    ABCMeta,
    abstractproperty)

import json
import os
import time
import uuid
import yaml
from retrying import retry
from urllib import urlretrieve
from contextlib import contextmanager
from distutils.version import LooseVersion

import jinja2
import retrying
import sh
from fabric import api as fabric_api
from fabric import context_managers as fabric_context_managers

from cosmo_tester.framework import util

from cloudify_cli.constants import DEFAULT_TENANT_NAME

HEALTHY_STATE = 'OK'
REMOTE_PRIVATE_KEY_PATH = '/etc/cloudify/key.pem'
REMOTE_PUBLIC_KEY_PATH = '/etc/cloudify/public_key'
REMOTE_OPENSTACK_CONFIG_PATH = '/etc/cloudify/openstack_config.json'
SANITY_MODE_FILE_PATH = '/opt/manager/sanity_mode'
RSYNC_SCRIPT_URL = 'https://raw.githubusercontent.com/cloudify-cosmo/cloudify-dev/master/scripts/rsync.sh'  # NOQA

MANAGER_API_VERSIONS = {
    'master': 'v3.1',
    '4.6': 'v3.1',
    '4.5.5': 'v3.1',
    '4.5': 'v3.1',
    '4.4': 'v3.1',
    '4.3.1': 'v3',
    '4.2': 'v3',
}

ATTRIBUTES = util.get_attributes()


class VM(object):
    __metaclass__ = ABCMeta

    def __init__(self, upload_plugins=False):
        """Mainly here for compatibility with other VM types"""
        self.upload_plugins = upload_plugins

    def create(
            self,
            index,
            public_ip_address,
            private_ip_address,
            networks,
            rest_client,
            ssh_key,
            cfy,
            attributes,
            logger,
            tmpdir,
    ):
        self.index = index
        self.ip_address = public_ip_address
        self.private_ip_address = private_ip_address
        self.client = rest_client
        self.deleted = False
        self._ssh_key = ssh_key
        self._cfy = cfy
        self._attributes = attributes
        self._logger = logger
        self._openstack = util.create_openstack_client()
        self._tmpdir = os.path.join(tmpdir, str(index))

    @contextmanager
    def ssh(self, **kwargs):
        with fabric_context_managers.settings(
                host_string=self.ip_address,
                user=self._attributes.default_linux_username,
                key_filename=self._ssh_key.private_key_path,
                abort_exception=Exception,
                **kwargs):
            yield fabric_api

    def __str__(self):
        return 'Cloudify Test VM ({image}) [{index}:{ip}]'.format(
            image=self.image_name,
            index=self.index,
            ip=self.ip_address,
        )

    @property
    def server_id(self):
        """Returns this server's Id from the terraform outputs."""
        key = 'server_id_{}'.format(self.index)
        return self._attributes[key]

    def delete(self):
        """Deletes this instance from the OpenStack envrionment."""
        self._logger.info('Deleting server.. [id=%s]', self.server_id)
        self._openstack.compute.delete_server(self.server_id)
        self._wait_for_server_to_be_deleted()
        self.deleted = True

    @retrying.retry(stop_max_attempt_number=12, wait_fixed=5000)
    def _wait_for_server_to_be_deleted(self):
        self._logger.info('Waiting for server to terminate..')
        servers = [x for x in self._openstack.compute.servers()
                   if x.id == self.server_id]
        if servers:
            self._logger.info('- server.status = %s', servers[0].status)
        assert len(servers) == 0
        self._logger.info('Server terminated!')

    def verify_services_are_running(self):
        return True

    def use(self, tenant=None):
        return True

    def upload_plugin(self, plugin_name):
        return True

    def upload_necessary_files(self):
        return True

    @property
    def ssh_key(self):
        return self._ssh_key

    def get_remote_file(self, remote_path, local_path, use_sudo=True):
        """ Dump the contents of the remote file into the local path """

        with self.ssh() as fabric_ssh:
            fabric_ssh.get(
                remote_path,
                local_path,
                use_sudo=use_sudo
            )

    def put_remote_file(self, remote_path, local_path, use_sudo=True):
        """ Dump the contents of the local file into the remote path """

        with self.ssh() as fabric_ssh:
            fabric_ssh.put(
                local_path,
                remote_path,
                use_sudo=use_sudo
            )

    def get_remote_file_content(self, remote_path, use_sudo=True):
        tmp_local_path = os.path.join(self._tmpdir, str(uuid.uuid4()))

        try:
            self.get_remote_file(remote_path, tmp_local_path, use_sudo)
            with open(tmp_local_path, 'r') as f:
                content = f.read()
        finally:
            if os.path.exists(tmp_local_path):
                os.unlink(tmp_local_path)
        return content

    def put_remote_file_content(self, remote_path, content, use_sudo=True):
        tmp_local_path = os.path.join(self._tmpdir, str(uuid.uuid4()))

        try:
            with open(tmp_local_path, 'w') as f:
                f.write(content)

            self.put_remote_file(remote_path, tmp_local_path, use_sudo)

        finally:
            if os.path.exists(tmp_local_path):
                os.unlink(tmp_local_path)

    def run_command(self, command, use_sudo=False):
        with self.ssh() as fabric_ssh:
            if use_sudo:
                return fabric_ssh.sudo(command)
            else:
                return fabric_ssh.run(command)

    def get_node_id(self):
        node_id_parts = self.run_command('cfy_manager node get-id').split(': ')
        if len(node_id_parts) < 2:
            raise RuntimeError('Status reporter is not installed')
        return node_id_parts[1]

    image_name = ATTRIBUTES['default_linux_image_name']
    username = ATTRIBUTES['default_linux_username']
    branch_name = 'master'


class _CloudifyManager(VM):

    def __init__(self, upload_plugins=True):
        self.upload_plugins = upload_plugins

    def create(
            self,
            index,
            public_ip_address,
            private_ip_address,
            networks,
            rest_client,
            ssh_key,
            cfy,
            attributes,
            logger,
            tmpdir
    ):
        self.index = index
        self.ip_address = public_ip_address
        self.private_ip_address = private_ip_address
        self.client = rest_client
        self.deleted = False
        self.networks = networks
        self._ssh_key = ssh_key
        self._cfy = cfy
        self._attributes = attributes
        self._logger = logger
        self._rsync_path = None
        self._tmpdir = os.path.join(tmpdir, str(uuid.uuid4()))
        os.makedirs(self._tmpdir)
        self._openstack = util.create_openstack_client()
        self.additional_install_config = {}

    def upload_necessary_files(self):
        self._logger.info('Uploading necessary files to %s', self)
        openstack_config_file = self._create_openstack_config_file()
        with self.ssh() as fabric_ssh:
            openstack_json_path = REMOTE_OPENSTACK_CONFIG_PATH
            fabric_ssh.sudo('mkdir -p "{}"'.format(
                os.path.dirname(REMOTE_PRIVATE_KEY_PATH)))
            fabric_ssh.put(openstack_config_file,
                           openstack_json_path,
                           use_sudo=True)

            fabric_ssh.put(self._ssh_key.private_key_path,
                           REMOTE_PRIVATE_KEY_PATH,
                           use_sudo=True)
            fabric_ssh.put(self._ssh_key.public_key_path,
                           REMOTE_PUBLIC_KEY_PATH,
                           use_sudo=True)

            fabric_ssh.sudo('chown root:cfyuser {key_file}'.format(
                key_file=REMOTE_PRIVATE_KEY_PATH,
            ))
            fabric_ssh.sudo('chown root:cfyuser {key_file}'.format(
                key_file=REMOTE_PUBLIC_KEY_PATH,
            ))

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
        with self.ssh() as fabric_ssh:

            fabric_ssh.sudo('mkdir -p "{}"'.format(
                os.path.dirname(SANITY_MODE_FILE_PATH)))

            fabric_ssh.sudo('echo sanity >> "{0}"'.format(
                SANITY_MODE_FILE_PATH))
            fabric_ssh.sudo('chown cfyuser:cfyuser {sanity_mode}'.format(
                sanity_mode=SANITY_MODE_FILE_PATH,
            ))
            fabric_ssh.sudo('chmod 440 {sanity_mode}'.format(
                sanity_mode=SANITY_MODE_FILE_PATH,
            ))

    def upload_plugin(self, plugin_name, tenant_name=DEFAULT_TENANT_NAME):
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

        # versions newer than 4.2 support passing yaml files
        yaml_snippet = ''
        if LooseVersion(self.branch_name) > LooseVersion('4.2'):
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
            try:
                self.use()
                command = [plugin['wgn_url'], '-t', tenant_name]
                if yaml_snippet:
                    command += ['--yaml-path', plugin['plugin_yaml_url']]
                self._cfy.plugins.upload(command)
            except Exception:
                # This is needed for 3.4 managers. local cfy isn't
                # compatible and cfy isn't installed in the image
                self.client.plugins.upload(plugin['wgn_url'])

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
        return 'Cloudify manager [{}:{}]'.format(self.index, self.ip_address)

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

    @property
    def server_id(self):
        """Returns this server's Id from the terraform outputs."""
        key = 'server_id_{}'.format(self.index)
        return self._attributes[key]

    @retrying.retry(stop_max_attempt_number=6 * 10, wait_fixed=10000)
    def verify_services_are_running(self):
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

        self._logger.info('Verifying all services are running on manager%d..',
                          self.index)

        manager_status = self.client.manager.get_status()
        if manager_status['status'] == HEALTHY_STATE:
            return

        for display_name, service in manager_status['services'].items():
            assert service['status'] == 'Active', \
                'service {0} is in {1} state'.format(
                    display_name, service['status'])

    @abstractproperty
    def branch_name(self):
        raise NotImplementedError()

    @property
    def image_name(self):
        image_name = ATTRIBUTES['cloudify_manager_{}_image_name'.format(
            self.branch_name.replace('.', '_'))]
        if ATTRIBUTES['default_manager_distro'] == 'rhel':
            image_name += '-rhel'
        return image_name

    @property
    def api_version(self):
        return MANAGER_API_VERSIONS[self.branch_name]

    @property
    def rsync_path(self):
        if not self._rsync_path:
            self._rsync_path = os.path.join(self._tmpdir, 'rsync.sh')
            urlretrieve(RSYNC_SCRIPT_URL, self._rsync_path)
            os.chmod(self._rsync_path, 0o755)  # Make the script executable

        return self._rsync_path

    # passed to cfy. To be overridden in pre-4.0 versions
    restore_tenant_name = None
    tenant_name = 'default_tenant'

    def stop_for_user_input(self):
        """
        Print out a helpful ssh command to allow the user to connect to the
        current manager, and then wait for user input to continue the test
        """
        self._logger.info('#' * 80)
        self._logger.info(
            '\nssh -o StrictHostKeyChecking=no {user}@{ip} -i {key}'.format(
                user=self._attributes.default_linux_username,
                ip=self.ip_address,
                key=self._ssh_key.private_key_path)
        )
        raw_input('You can now connect to the manager')

    def sync_local_code_to_manager(self):
        self._logger.info('Syncing local code to the manager')
        cmd = ' '.join([
            self.rsync_path,
            self.ip_address,
            self._attributes.default_linux_username,
            self._ssh_key.private_key_path
        ])
        self._logger.info('Running command:\n{0}'.format(cmd))
        os.system(cmd)

    def teardown(self):
        with self.ssh() as fabric_ssh:
            fabric_ssh.run('cfy_manager remove --force')
            fabric_ssh.sudo('yum remove -y cloudify-manager-install')

    def _create_config_file(self, upload_license=True):
        config_file = self._tmpdir / 'config_{0}.yaml'.format(self.index)
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
            'Install config:\n{0}'.format(install_config_str))
        config_file.write_text(install_config_str)
        return config_file

    def bootstrap(self, enter_sanity_mode=True, upload_license=False,
                  blocking=True):
        manager_install_rpm = \
            ATTRIBUTES.cloudify_manager_install_rpm_url.strip() or \
            util.get_manager_install_rpm_url()

        install_config = self._create_config_file(
            upload_license and not util.is_community())
        install_rpm_file = 'cloudify-manager-install.rpm'
        with self.ssh() as fabric_ssh:
            fabric_ssh.run('mkdir -p /tmp/bs_logs')
            fabric_ssh.put(
                install_config,
                '/tmp/cloudify.conf'
            )
            if upload_license:
                fabric_ssh.put(
                    util.get_resource_path('test_valid_paying_license.yaml'),
                    '/tmp/test_valid_paying_license.yaml'
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

            install_file = self._tmpdir / 'install_{0}.yaml'.format(self.index)
            install_file.write_text(install_command)
            fabric_ssh.put(install_file, '/tmp/bootstrap_script')

            fabric_ssh.run('nohup bash /tmp/bootstrap_script')

        if blocking:
            while True:
                if self.bootstrap_is_complete():
                    break
                else:
                    time.sleep(5)
            if enter_sanity_mode:
                self.enter_sanity_mode()

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
            ).strip()

            if result == 'done':
                self._logger.info('Bootstrap complete.')
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

    @retrying.retry(stop_max_attempt_number=60, wait_fixed=1000)
    def wait_for_manager(self):
        manager_status = self.client.manager.get_status()
        if manager_status['status'] != HEALTHY_STATE:
            raise StandardError(
                'Timed out: Reboot did not complete successfully'
            )


class _OldStatusFormat(object):
    """Mixin for a CloudifyManager class, making it use pre-5.0.5 status

    In 5.0.5, the format of the status response changed, so VM classes
    that represent a pre-5.0.5 manager must use this to use the old way
    of getting status.
    """
    @retrying.retry(stop_max_attempt_number=6 * 10, wait_fixed=10000)
    def verify_services_are_running(self):
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

        self._logger.info('Verifying all services are running on manager%d..',
                          self.index)
        status = self.client.manager.get_status()
        for service in status['services']:
            for instance in service['instances']:
                if all(service not in instance['Id'] for
                       service in ['postgresql', 'rabbitmq']):
                    assert instance['SubState'] == 'running', \
                        'service {0} is in {1} state'.format(
                            service['display_name'], instance['SubState'])

    @retrying.retry(stop_max_attempt_number=60, wait_fixed=1000)
    def wait_for_manager(self):
        status = self.client.manager.get_status()
        for service in status['services']:
            for instance in service['instances']:
                if any(service not in instance['Id'] for
                       service in ['postgresql', 'rabbitmq']):
                    if instance['state'] != 'running':
                        raise StandardError(
                            'Timed out: Reboot did not complete successfully'
                        )


class _CloudifyDatabaseOnly(_CloudifyManager):
    """
    This class represents an instance of a Cloudify Database only

    Most of the inherited functions here are to avoid any incorrect usage of
    the class since most of these functions rely on the manager existing on the
    machine.
    """

    def __init__(self):
        super(_CloudifyDatabaseOnly, self).__init__(upload_plugins=False)

    def __str__(self):
        return 'Cloudify Manager - database only VM ({image}) [{index}:{ip}]' \
            .format(image=self.image_name,
                    index=self.index,
                    ip=self.ip_address, )

    @property
    def branch_name(self):
        pass

    def create(
            self,
            index,
            public_ip_address,
            private_ip_address,
            networks,
            rest_client,
            ssh_key,
            cfy,
            attributes,
            logger,
            tmpdir
    ):
        self.index = index
        self.ip_address = public_ip_address
        self.private_ip_address = private_ip_address
        self.client = rest_client
        self.deleted = False
        self._ssh_key = ssh_key
        self._cfy = cfy
        self._attributes = attributes
        self._logger = logger
        self._tmpdir = os.path.join(tmpdir, str(uuid.uuid4()))
        os.makedirs(self._tmpdir)
        self.additional_install_config = {}

    @retrying.retry(stop_max_attempt_number=6 * 10, wait_fixed=10000)
    def verify_services_are_running(self):
        with self.ssh() as fabric_ssh:
            # validate PostgreSQL server is running
            try:
                fabric_ssh.sudo('su -c "psql -l" postgres &> /dev/null')
                self._logger.info('PostgreSQL active')
                return True
            except Exception as e:
                self._logger.warn(
                    'PostgreSQL is not in an active state, Error: {0}.'
                    ' Retrying...'.format(e.message))

    def bootstrap(self, enter_sanity_mode=False, upload_license=False):
        super(_CloudifyDatabaseOnly, self).bootstrap(enter_sanity_mode,
                                                     upload_license)

    def api_version(self):
        pass

    def wait_for_manager(self):
        pass

    def stop_for_user_input(self):
        pass

    def remote_private_key_path(self):
        pass

    def use(self, tenant=None, profile_name=None):
        pass

    def upload_necessary_files(self):
        pass

    def upload_plugin(self, plugin_name, tenant_name=DEFAULT_TENANT_NAME):
        pass


class _CloudifyMessageQueueOnly(_CloudifyManager):
    """
    This class represents an instance of a Cloudify Message Queue only

    Most of the inherited functions here are to avoid any incorrect usage of
    the class since most of these functions rely on the manager existing on the
    machine.
    """

    def __init__(self):
        super(_CloudifyMessageQueueOnly, self).__init__(upload_plugins=False)

    def __str__(self):
        return 'Cloudify Manager - message queue only VM ({image}) ' \
               '[{index}:{ip}]' \
            .format(image=self.image_name,
                    index=self.index,
                    ip=self.ip_address, )

    @property
    def branch_name(self):
        pass

    def create(
            self,
            index,
            public_ip_address,
            private_ip_address,
            networks,
            rest_client,
            ssh_key,
            cfy,
            attributes,
            logger,
            tmpdir
    ):
        self.index = index
        self.ip_address = public_ip_address
        self.private_ip_address = private_ip_address
        self.client = rest_client
        self.deleted = False
        self._ssh_key = ssh_key
        self._cfy = cfy
        self._attributes = attributes
        self._logger = logger
        self._tmpdir = os.path.join(tmpdir, str(uuid.uuid4()))
        os.makedirs(self._tmpdir)
        self.additional_install_config = {'rabbitmq': {}}

    @retrying.retry(stop_max_attempt_number=6 * 10, wait_fixed=10000)
    def verify_services_are_running(self):
        with self.ssh() as fabric_ssh:
            # validate PostgreSQL server is running
            try:
                fabric_ssh.sudo('rabbitmqctl -n rabbit@localhost '
                                'list_users &> /dev/null')
                self._logger.info('RabbitMQ active')
                return True
            except Exception as e:
                self._logger.warn(
                    'RabbitMQ is not in an active state, Error: {0}.'
                    ' Retrying...'.format(e.message))

    def api_version(self):
        pass

    def wait_for_manager(self):
        pass

    def stop_for_user_input(self):
        pass

    def remote_private_key_path(self):
        pass

    def use(self, tenant=None, profile_name=None):
        pass

    def upload_necessary_files(self):
        pass

    def upload_plugin(self, plugin_name, tenant_name=DEFAULT_TENANT_NAME):
        pass


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


class Cloudify4_2Manager(_OldStatusFormat, _CloudifyManager):
    branch_name = '4.2'


class Cloudify4_3_1Manager(_OldStatusFormat, _CloudifyManager):
    branch_name = '4.3.1'


class Cloudify4_4Manager(_OldStatusFormat, _CloudifyManager):
    branch_name = '4.4'


class Cloudify4_5Manager(_OldStatusFormat, _CloudifyManager):
    branch_name = '4.5'


class Cloudify4_5_5Manager(_OldStatusFormat, _CloudifyManager):
    branch_name = '4.5.5'


class Cloudify4_6Manager(_OldStatusFormat, _CloudifyManager):
    branch_name = '4.6'


class Cloudify4_6Manager_ClusterJoined(Cloudify4_6Manager):
    def verify_services_are_running(self):
        pass


class CloudifyMasterManager(_CloudifyManager):
    branch_name = 'master'
    image_name_attribute = 'cloudify_manager_image_name_prefix'

    image_name = get_latest_manager_image_name()

    # The MTU is set to 1450 because we're using a static BOOTPROTO here (as
    # opposed to DHCP), which sets a lower default by default
    NETWORK_CONFIG_TEMPLATE = textwrap.dedent("""
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

        self._logger.info('Adding extra NICs...')

        # Need to do this for each network except 0 (eth0 is already enabled)
        for i in range(1, len(self.networks)):
            network_file_path = self._tmpdir / 'network_cfg_{0}'.format(i)
            ip_addr = self.networks['network_{0}'.format(i)]
            config_content = self.NETWORK_CONFIG_TEMPLATE.format(i, ip_addr)

            # Create and copy the interface config
            network_file_path.write_text(config_content)
            with self.ssh() as fabric_ssh:
                fabric_ssh.put(
                    network_file_path,
                    '/etc/sysconfig/network-scripts/ifcfg-eth{0}'.format(i),
                    use_sudo=True
                )
                # Start the interface
                fabric_ssh.sudo('ifup eth{0}'.format(i))


IMAGES = {
    '4.2': Cloudify4_2Manager,
    '4.3.1': Cloudify4_3_1Manager,
    '4.4': Cloudify4_4Manager,
    '4.5': Cloudify4_5Manager,
    '4.5.5': Cloudify4_5_5Manager,
    '4.6': Cloudify4_6Manager,
    'master': CloudifyMasterManager,
    'centos': VM,
}

CURRENT_MANAGER = IMAGES['master']


class TestHosts(object):
    __metaclass__ = ABCMeta

    def __init__(self,
                 cfy,
                 ssh_key,
                 tmpdir,
                 attributes,
                 logger,
                 number_of_instances=1,
                 instances=None,
                 tf_template=None,
                 template_inputs=None,
                 upload_plugins=True,
                 request=None):
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
        self._terraform = util.sh_bake(sh.terraform)
        self._terraform_inputs_file = self._tmpdir / 'terraform-vars.json'
        self._tf_template = tf_template or 'openstack-vm.tf.template'
        self.preconfigure_callback = None
        if instances is not None:
            self.instances = instances
        else:
            self.instances = [
                CURRENT_MANAGER(upload_plugins=upload_plugins)
                for _ in range(number_of_instances)]
        self._template_inputs = template_inputs or {'servers': self.instances}
        self._request = request

    def _bootstrap_managers(self):
        pass

    def _get_server_flavor(self):
        return self._attributes.manager_server_flavor_name

    def create(self):
        """Creates the infrastructure for a Cloudify manager.

        The credentials file and private key file for SSHing
        to provisioned VMs are uploaded to the server."""
        self._logger.info('Creating image based cloudify instances: '
                          '[number_of_instances=%d]', len(self.instances))

        terraform_template_file = self._tmpdir / 'openstack-vm.tf'

        input_file = util.get_resource_path(
            'terraform/{0}'.format(self._tf_template)
        )
        with open(input_file, 'r') as f:
            tf_template = f.read()

        output = jinja2.Template(tf_template).render(self._template_inputs)

        terraform_template_file.write_text(output)

        self._terraform_inputs_file.write_text(json.dumps({
            'resource_suffix': str(uuid.uuid4()),
            'public_key_path': self._ssh_key.public_key_path,
            'private_key_path': self._ssh_key.private_key_path,
            'flavor': self._get_server_flavor()
        }, indent=2))

        try:
            with self._tmpdir:
                self._terraform.apply(['-var-file',
                                       self._terraform_inputs_file])
                outputs = util.AttributesDict(
                    {k: v['value'] for k, v in yaml.safe_load(
                        self._terraform.output(
                            ['-json']).stdout).items()})
            self._attributes.update(outputs)

            self._update_instances_list(outputs)

            if self.preconfigure_callback:
                self.preconfigure_callback(self.instances)

            self._bootstrap_managers()

            for instance in self.instances:
                instance.verify_services_are_running()
                instance.upload_necessary_files()
                if instance.upload_plugins:
                    instance.upload_plugin(
                        self._attributes.default_openstack_plugin)

            self._logger.info('Test hosts successfully created!')

        except Exception as e:
            self._logger.error(
                'Error creating image based hosts: %s', e)
            try:
                self.destroy()
            except sh.ErrorReturnCode as ex:
                self._logger.error('Error on terraform destroy: %s', ex)
            raise

    def destroy(self):
        """Destroys the infrastructure. """
        try:
            self._save_manager_logs()
        except Exception as e:
            self._logger.info(
                "Unable to save logs due to exception: {}".format(str(e)))
        finally:
            self._logger.info('Destroying test hosts..')
            with self._tmpdir:
                self._terraform.destroy(
                    ['-var-file', self._terraform_inputs_file, '-force']
                )

    def _update_instances_list(self, outputs):
        for i, instance in enumerate(self.instances):
            public_ip_address = outputs['public_ip_address_{}'.format(i)]
            private_ip_address = outputs['private_ip_address_{}'.format(i)]
            # Some templates don't expose networks as outputs
            networks = outputs.get('networks_{}'.format(i), {})
            # Convert unicode to strings, in order to avoid ruamel issues
            # when loading this dict into the config.yaml
            networks = {str(k): str(v) for k, v in networks.items()}
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
            instance.create(
                i,
                public_ip_address,
                private_ip_address,
                networks,
                rest_client,
                self._ssh_key,
                self._cfy,
                self._attributes,
                self._logger,
                self._tmpdir
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
                                  '{}, since server has been deleted or not '
                                  'initialized.'.format(i))
            else:
                self._save_logs_for_instance(instance, logs_dir, i)

        self._logger.debug('_save_manager_logs completed')

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def _save_logs_for_instance(self, instance, logs_dir, instance_index):
        def _generate_prefix():
            """
            :return: log tar file prefix in the following format:
                <instance_class_name>__[<pytest_params_if_exist>__] +
                    + <index_number_in_instances_list>__<terraform_id>__
            """
            prefix = '{}__'.format(instance.__class__.__name__)
            if self._request and hasattr(self._request, 'param'):
                prefix += '{}__'.format(self._request.param)
            prefix += 'index_{}__'.format(instance_index)
            return prefix

        self._logger.info('Attempting to download logs for Cloudify Manager '
                          'with ID: {}...'.format(instance.server_id))
        self._logger.info('Switching profiles...')
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


class BootstrappableHosts(TestHosts):
    """Creates a medium linux image that can be bootstrapped later."""
    def __init__(self, *args, **kwargs):
        super(BootstrappableHosts, self).__init__(*args, **kwargs)
        for manager in self.instances:
            manager.image_name = self._attributes.default_linux_image_name

    def _get_server_flavor(self):
        return self._attributes.medium_flavor_name


class BootstrapBasedCloudifyManagers(BootstrappableHosts):
    """Bootstraps a Cloudify manager using manager install RPM."""
    def _bootstrap_managers(self):
        super(BootstrapBasedCloudifyManagers, self)._bootstrap_managers()

        for manager in self.instances:
            manager.bootstrap()
