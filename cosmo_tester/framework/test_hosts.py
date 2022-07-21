import copy
from datetime import datetime
import functools
import hashlib
import json
import os
import random
import re
import string
import socket
import subprocess
import sys
import time
import uuid
import warnings
import yaml

with warnings.catch_warnings():
    # Fabric maintenance is lagging a bit so let's suppress these warnings.
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from fabric import Connection
from ipaddress import ip_address, ip_network
from paramiko.ssh_exception import SSHException
from packaging.version import parse as parse_version
import requests
import retrying
import textwrap
import winrm

from cloudify_rest_client.exceptions import CloudifyClientError

from cosmo_tester.framework import util
from cosmo_tester.framework.constants import CLOUDIFY_TENANT_HEADER

HEALTHY_STATE = 'OK'
RSYNC_LOCATIONS = ['/etc',
                   '/opt',
                   '/var',
                   '/usr']


def only_manager(func):
    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        if not self.is_manager:
            raise RuntimeError('This is not a manager')
        return func(self, *args, **kwargs)
    return wrapped


def ensure_conn(func):
    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        if self.windows:
            # We don't maintain a conn for windows currently
            return func(self, *args, **kwargs)
        if self._conn is None or self._conn.transport is None:
            _make_connection(self)
        # SFTP session gets cached and breaks after reboots or conn drops.
        # Someone has a PR to fabric in-flight since Nov 2021.
        self._conn._sftp = None
        try:
            self._conn.transport.open_session().close()
        except Exception as err:
            self._logger.warning('SSH connection failure: %s', err)
            _make_connection(self)
            self._conn.transport.open_session().close()
        return func(self, *args, **kwargs)
    return wrapped


@retrying.retry(stop_max_attempt_number=5, wait_fixed=3000)
def _make_connection(vm):
    vm._conn = Connection(
        host=vm.ip_address,
        user=vm.username,
        connect_kwargs={
            'key_filename': [vm.private_key_path],
        },
        port=22,
        connect_timeout=3,
    )
    vm._conn.open()
    vm._conn.transport.set_keepalive(15)


class VM(object):
    def __init__(self, image_type, test_config, bootstrappable=False):
        self.image_name = None
        self.userdata = ""
        self.username = None
        self.password = None
        self.api_ca_path = None
        self.enable_ssh_wait = True
        self.should_finalize = True
        self.restservice_expected = False
        self.client = None
        self._test_config = test_config
        self.windows = 'windows' in image_type
        self._tmpdir_base = None
        self.bootstrappable = bootstrappable
        self.image_type = image_type
        self.is_manager = self._is_manager_image_type()
        self.reboot_required = False
        self._set_image_details()
        if self.windows:
            self.prepare_for_windows()
        if self.is_manager:
            self.basic_install_config = {
                'manager': {
                    'security': {
                        'admin_username': self._test_config[
                            'test_manager']['username'],
                        'admin_password': util.generate_password(),
                    },
                },
                'sanity': {'skip_sanity': True},
            }

    def assign(
            self,
            public_ip_address,
            private_ip_address,
            networks,
            ssh_key,
            logger,
            tmpdir,
            node_instance_id,
            deployment_id,
            server_id,
            server_index,
    ):
        self.ip_address = public_ip_address
        self.private_ip_address = private_ip_address
        self._ssh_key = ssh_key
        self._logger = logger
        self._tmpdir_base = tmpdir
        self._tmpdir = os.path.join(tmpdir, public_ip_address)
        os.makedirs(self._tmpdir)
        self.node_instance_id = node_instance_id
        self.deployment_id = deployment_id
        self.server_id = server_id
        # This is overridden in some cluster tests
        self.friendly_name = '{} ({})'.format(server_id, private_ip_address)
        self.server_index = server_index
        if self.is_manager:
            self.basic_install_config['manager']['public_ip'] = \
                str(public_ip_address)
            self.basic_install_config['manager']['private_ip'] = \
                str(private_ip_address)
            self.basic_install_config['manager']['hostname'] = str(server_id)
            self.networks = networks
            self.install_config = copy.deepcopy(self.basic_install_config)
        self._create_conn_script()
        self._conn = None

    def _create_conn_script(self):
        script_path = self._tmpdir_base / '{prefix}_{index}'.format(
            prefix='rdp' if self.windows else 'ssh',
            index=self.server_index)
        if self.windows:
            script_content = (
                "xfreerdp /u:{user} /p:'{password}' "
                '/w:1366 /h:768 /v:{addr}'
            ).format(
                user=self.username,
                password=self.password,
                addr=self.ip_address,
            )
        else:
            # Don't check this call- it might fail due to missing known_hosts
            # file or similar, and we shouldn't fail the test because of that.
            subprocess.call(['ssh-keygen', '-R', self.ip_address])
            script_content = (
                'ssh -i {key} -o StrictHostKeyChecking=no {connstr} ${{*}}\n'
            ).format(
                key=self._ssh_key.private_key_path,
                connstr='{}@{}'.format(self.username, self.ip_address),
            )
        with open(script_path, 'w') as fh:
            fh.write(script_content)
        subprocess.check_call(['chmod', '+x', script_path])

    def log_action(self, action):
        """Log that we're doing something with this node."""
        self._logger.info('%s on %s', action, self.friendly_name)

    def prepare_for_windows(self):
        """Prepare this VM to be created as a windows VM."""
        add_firewall_cmd = "&netsh advfirewall firewall add rule"
        password = ''.join(random.choice(string.ascii_letters + string.digits)
                           for _ in range(16))
        # To meet complexity requirements- the above should be hard enough to
        # crack for a short lived test VM
        password += '!'

        self.enable_ssh_wait = False
        self.restservice_expected = False
        self.should_finalize = False

        self.userdata = """#ps1_sysnative
$PSDefaultParameterValues['*:Encoding'] = 'utf8'

Write-Host "## Configuring WinRM and firewall rules.."
winrm quickconfig -q
winrm set winrm/config              '@{{MaxTimeoutms="1800000"}}'
winrm set winrm/config/winrs        '@{{MaxMemoryPerShellMB="300"}}'
winrm set winrm/config/service      '@{{AllowUnencrypted="true"}}'
winrm set winrm/config/service/auth '@{{Basic="true"}}'
{fw_cmd} name="WinRM 5985" protocol=TCP dir=in localport=5985 action=allow
{fw_cmd} name="WinRM 5986" protocol=TCP dir=in localport=5986 action=allow

Write-Host "## Setting password for Admin user.."
$user = [ADSI]"WinNT://localhost/{user}"
$user.SetPassword("{password}")
$user.SetInfo()""".format(fw_cmd=add_firewall_cmd,
                          user=self.username,
                          password=password)

        self.password = password

    @retrying.retry(stop_max_attempt_number=120, wait_fixed=3000)
    def wait_for_winrm(self):
        self._logger.info('Checking Windows VM %s is up...', self.ip_address)
        try:
            self.run_command('Write-Output "Testing winrm."',
                             powershell=True)
        except Exception as err:
            self._logger.warning('...failed: {err}'.format(err=err))
            raise
        self._logger.info('...Windows VM is up.')

    def get_windows_remote_file_content(self, path):
        return self.run_command(
            'Get-Content -Path {}'.format(path),
            powershell=True).std_out

    # We're allowing about 5 minutes in case of /really/ slow VM start/restart
    @retrying.retry(stop_max_attempt_number=100, wait_fixed=3000)
    def wait_for_ssh(self):
        if self.enable_ssh_wait:
            self.run_command('true')
            self.log_action('SSH check complete')

    @property
    def private_key_path(self):
        return self._ssh_key.private_key_path

    def __str__(self):
        if self.is_manager:
            return 'Cloudify manager [{}]'.format(self.ip_address)
        return 'Cloudify Test VM ({image}) [{ip}]'.format(
            image=self.image_name,
            ip=self.ip_address,
        )

    def stop(self):
        """Stops this instance."""
        self._logger.info('Stopping server.. [id=%s]', self.server_id)
        # Previously, we were calling stop_server on openstack, which allowed
        # clean shutdown
        self.run_command('shutdown -h now', warn_only=True, use_sudo=True)
        while True:
            try:
                self.log_action('Checking connection')
                time.sleep(3)
            except (SSHException, socket.timeout, EOFError, TimeoutError):
                # Errors like 'Connection reset by peer' can occur during the
                # shutdown, but we should wait a little longer to give other
                # services time to stop
                time.sleep(3)
            if not self._conn.is_connected:
                # By this point everything should be down.
                self.log_action('Server stopped')
                break

    def finalize_preparation(self):
        """Complete preparations for using a new instance."""
        self._logger.info('Finalizing server preparations.')
        self.wait_for_ssh()
        if self.restservice_expected:
            # When creating the rest client here we can't check for SSL yet,
            # because the manager probably isn't up yet. Therefore, we'll just
            # make the client.
            self.client = self.get_rest_client(proto='http')
            self._logger.info('Checking rest service.')
            self.wait_for_manager()
            self._logger.info('Applying license.')
            self.apply_license()

    def _get_python_path(self):
        return self.run_command(
            'which python || which python3').stdout.strip()

    def get_distro(self):
        # Get the distro string we expect agents to be
        if self.windows:
            return 'windows'

        self.put_remote_file_content(
            '/tmp/get_distro',
            '''#! {python}
import platform

distro, _, codename = platform.dist()
print('{{}} {{}}'.format(distro, codename).lower())
'''.format(python=self._get_python_path()))
        self.run_command('chmod +x /tmp/get_distro')
        return self.run_command('/tmp/get_distro').stdout.strip()

    @property
    def ssh_key(self):
        return self._ssh_key

    @ensure_conn
    def get_remote_file(self, remote_path, local_path):
        """ Dump the contents of the remote file into the local path """
        # Similar to the way fabric1 did it
        remote_tmp = '/tmp/' + hashlib.sha1(
            remote_path.encode('utf-8')).hexdigest()
        self.run_command(
            'cp {} {}'.format(remote_path, remote_tmp),
            use_sudo=True,
        )
        self.run_command(
            'chmod 444 {}'.format(remote_tmp),
            use_sudo=True,
        )
        local_dir = os.path.dirname(local_path)
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)

        self._conn.get(
            remote_tmp,
            local_path,
        )

    @ensure_conn
    def put_remote_file(self, remote_path, local_path):
        """ Dump the contents of the local file into the remote path """
        if self.windows:
            with open(local_path) as fh:
                content = fh.read()
            self.put_remote_file_content(remote_path, content)
        else:
            remote_tmp = '/tmp/' + hashlib.sha1(
                remote_path.encode('utf-8')).hexdigest()
            self.run_command(
                'rm -rf {}'.format(remote_tmp),
                use_sudo=True,
            )
            # Similar to the way fabric1 did it
            self._conn.put(
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
        if self.windows:
            self.run_command(
                "Add-Content -Path {} -Value '{}'".format(
                    remote_path,
                    # Single quoted string will not be interpreted
                    # But single quotes must be represented in such a string
                    # with double single quotes
                    content.replace("'", "''"),
                ),
                powershell=True,
            )
        else:
            tmp_local_path = os.path.join(self._tmpdir, str(uuid.uuid4()))

            try:
                with open(tmp_local_path, 'w') as f:
                    f.write(content)

                self.put_remote_file(remote_path, tmp_local_path)

            finally:
                if os.path.exists(tmp_local_path):
                    os.unlink(tmp_local_path)

    @ensure_conn
    def run_command(self, command, use_sudo=False, warn_only=False,
                    hide_stdout=False, powershell=False):
        if self.windows:
            url = 'http://{host}:{port}/wsman'.format(host=self.ip_address,
                                                      port=5985)
            session = winrm.Session(url, auth=(self.username, self.password))
            self._logger.info('Running command: %s', command)
            runner = session.run_ps if powershell else session.run_cmd
            result = runner(command)
            self._logger.info('- stdout: %s', result.std_out)
            self._logger.info('- stderr: %s', result.std_err)
            self._logger.info('- status_code: %d', result.status_code)
            if not warn_only:
                assert result.status_code == 0
            # To allow the same calling conventions as linux commands
            result.stdout = result.std_out
            return result
        else:
            hide = 'stdout' if hide_stdout else None
            if use_sudo:
                return self._conn.sudo(command, warn=warn_only, hide=hide)
            else:
                return self._conn.run(command, warn=warn_only, hide=hide)

    @property
    @only_manager
    def mgr_password(self):
        return self.install_config['manager']['security']['admin_password']

    @only_manager
    def upload_init_script_plugin(self, tenant_name='default_tenant'):
        self._logger.info('Uploading init script plugin to %s', tenant_name)
        self._upload_plugin(
            'plugin/init_script_plugin-1.0.0-py27-none-any.zip',
            tenant_name)

    @only_manager
    def upload_test_plugin(self, tenant_name='default_tenant'):
        self._logger.info('Uploading test plugin to %s', tenant_name)
        self._upload_plugin(
            'plugin/test_plugin-1.0.0-py27-none-any.zip',
            tenant_name)

    def _upload_plugin(self, plugin_path, tenant_name):
        with util.set_client_tenant(self.client, tenant_name):
            try:
                self.client.plugins.upload(
                    util.get_resource_path(plugin_path),
                )
                self.wait_for_all_executions(include_system_workflows=True)
            except CloudifyClientError as err:
                if self._test_config['premium']:
                    raise
                # On community this can happen if multiple tests use the
                # same manager (because the first will upload the plugin and
                # the later test(s) will then conflict due to it existing).
                # Premium avoids this with multiple tenants.
                if 'already exists' in str(err):
                    pass
                else:
                    raise

    @only_manager
    @retrying.retry(stop_max_attempt_number=6 * 10, wait_fixed=10000)
    def verify_services_are_running(self):
        if not self.is_manager:
            return True

        # the manager-ip-setter script creates the `touched` file when it
        # is done.
        try:
            # will fail on bootstrap based managers
            self.run_command('supervisorctl -a | grep manager-ip-setter')
        except Exception:
            pass
        else:
            self._logger.info('Verify manager-ip-setter is done..')
            self.run_command('cat /opt/cloudify/manager-ip-setter/touched')

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

    @only_manager
    def get_installed_configs(self):
        conf_files = [
            conf_file.strip() for conf_file in
            self.run_command(
                'ls /etc/cloudify/*_config.yaml || true').stdout.split()
        ]
        return conf_files or ['/etc/cloudify/config.yaml']

    @only_manager
    def is_configured(self):
        services = self.run_command(
            'if [[ -d {confed_dir} ]]; then ls {confed_dir}; fi'.format(
                confed_dir='/etc/cloudify/.configured',
            )
        ).stdout.strip()
        return any(service in services for service in
                   ['database', 'manager', 'queue'])

    @only_manager
    def start_manager_services(self):
        if not self.is_configured():
            self._logger.info('No services configured')
            return
        for config_name in self.get_installed_configs():
            config_path = self._get_config_path(config_name)
            self._logger.info('Starting services using {}'.format(
                config_path))
            self.run_command('cfy_manager start -c {}'.format(config_path))

    @only_manager
    def stop_manager_services(self):
        if not self.is_configured():
            self._logger.info('No services configured')
            return
        for config_name in self.get_installed_configs():
            config_path = self._get_config_path(config_name)
            self._logger.info('Stopping services using {}'.format(
                config_path))
            self.run_command('cfy_manager stop -c {}'.format(config_path))

    @only_manager
    def teardown(self, kill_certs=True):
        self._logger.info('Tearing down using any installed configs')
        if self.is_configured():
            for config_name in self.get_installed_configs():
                config_path = self._get_config_path(config_name)
                self._logger.info('Tearing down using {}'.format(config_path))
                self.run_command(
                    'cfy_manager remove -c {}'.format(config_path))
        else:
            self._logger.info('No services configured')
        if kill_certs:
            self._logger.info('Removing certs directory')
            self.run_command('sudo rm -rf /etc/cloudify/ssl')
        if self.api_ca_path and os.path.exists(self.api_ca_path):
            os.unlink(self.api_ca_path)

    @only_manager
    def _create_config_file(self, upload_license=True):
        config_file = self._tmpdir / 'config_{0}.yaml'.format(self.ip_address)
        cloudify_license_path = \
            '/tmp/test_valid_paying_license.yaml' if upload_license else ''
        self.install_config['manager'][
            'cloudify_license_path'] = cloudify_license_path
        install_config_str = yaml.safe_dump(self.install_config)

        self._logger.info(
            'Install config:\n%s', str(install_config_str))
        config_file.write_text(install_config_str)
        return config_file

    @only_manager
    def apply_license(self):
        license = util.get_resource_path('test_valid_paying_license.yaml')
        self.client.license.upload(license)

    @only_manager
    def apply_override(self, override_name):
        override_path = self._test_config['override'][override_name]
        if not override_path:
            self._logger.info('No override set for %s', override_name)
            return

        override_subdirs = ['cfy_manager']
        remote_paths = [
            '/opt/cloudify/cfy_manager/lib/python3.6/site-packages/'
        ]

        local_tar_path = self._tmpdir_base / 'override_{}.tar.gz'.format(
            override_name,
        )
        remote_tar_path = '/tmp/override_{}.tar.gz'.format(override_name)
        subprocess.check_call(
            [
                'tar', '-czf', local_tar_path, *override_subdirs
            ],
            cwd=override_path,
        )
        self.put_remote_file(remote_tar_path, local_tar_path)

        for remote_path in remote_paths:
            self._logger.info('Removing existing files for %s', override_name)
            for subdir in override_subdirs:
                subdir_path = remote_path + subdir
                self.run_command('rm -r {}'.format(subdir_path),
                                 use_sudo=True)
            self._logger.info('Extracting new files from %s to %s for %s',
                              remote_tar_path, remote_path, override_name)
            self.run_command(
                'bash -c "cd {remote_path} '
                '&& tar -xzf {archive_path}"'.format(
                    remote_path=remote_path,
                    archive_path=remote_tar_path,
                ),
                use_sudo=True,
            )

    @only_manager
    def _get_config_path(self, config_name=None):
        if config_name:
            if config_name.startswith('/'):
                return config_name
            return '/etc/cloudify/{0}_config.yaml'.format(config_name)
        return '/etc/cloudify/config.yaml'

    @only_manager
    def bootstrap(self, upload_license=False,
                  blocking=True, restservice_expected=True, config_name=None,
                  include_sanity=False):
        if include_sanity:
            self.install_config['sanity']['skip_sanity'] = False
        self.wait_for_ssh()

        if self.image_type == 'master':
            # Only apply the overrides to the version being tested.
            # The others were already released, don't pretend changing them is
            # reasonable.
            self.apply_override('cloudify_manager_install')

        self.restservice_expected = restservice_expected
        install_config = self._create_config_file(
            upload_license and self._test_config['premium'])

        # If we leave this lying around on a compact cluster, we think we
        # finished bootstrapping every component after the first as soon
        # as we check it, because the first component did finish.
        self.run_command('rm -f /tmp/bootstrap_complete')

        self.run_command('mkdir -p /tmp/bs_logs')
        self.put_remote_file(
            '/tmp/cloudify.conf',
            install_config,
        )
        if upload_license:
            self.put_remote_file(
                '/tmp/test_valid_paying_license.yaml',
                util.get_resource_path('test_valid_paying_license.yaml'),
            )

        if config_name:
            dest_config_path = self._get_config_path(config_name)
            commands = [
                'sudo mv /tmp/cloudify.conf {0} > '
                '/tmp/bs_logs/0_mv 2>&1'.format(dest_config_path),
                'cfy_manager install -c {0} > '
                '/tmp/bs_logs/3_install 2>&1'.format(dest_config_path)
            ]
        else:
            commands = [
                'sudo mv /tmp/cloudify.conf /etc/cloudify/config.yaml > '
                '/tmp/bs_logs/0_mv 2>&1',
                'cfy_manager install > /tmp/bs_logs/3_install 2>&1'
            ]

        commands.append('touch /tmp/bootstrap_complete')

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

        self.run_command('nohup bash /tmp/bootstrap_script &>/dev/null &')

        if blocking:
            while True:
                if self.bootstrap_is_complete():
                    break
                else:
                    time.sleep(5)

    @only_manager
    def bootstrap_is_complete(self):
        # Using a bash construct because fabric seems to change its mind
        # about how non-zero exit codes should be handled frequently
        result = self.run_command(
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
            self.run_command('date > /tmp/cfy_mgr_last_check_time')
            if result == 'failed':
                self._logger.error('BOOTSTRAP FAILED!')
                # Get all the logs on failure
                self.run_command(
                    'cat /tmp/bs_logs/* || echo "No bs logs"'
                )
                # We return both the bootstrap logs (stdout of the command)
                # and the cfy_manager logs where possible as they may contain
                # differing information- e.g. the bootstrap log may complain
                # that it could not find the cfy_manager executable.
                # The bootstrap log (stdout) also contains the admin password,
                # which the cfy_manager.log does not.
                self._logger.error('===============================')
                self._logger.error('cfy_manager logs')
                self._logger.error('===============================')
                self.run_command(
                    'cat /var/log/cloudify/manager/cfy_manager.log '
                    '|| echo "No /var/log/cloudify/manager/cfy_manager.log"'
                )
                raise RuntimeError('Bootstrap failed.')
            else:
                self.run_command(
                    'tail -n5 /tmp/bs_logs/* || echo Waiting for logs'
                )
                self._logger.info('Bootstrap in progress...')
                return False

    @only_manager
    @retrying.retry(stop_max_attempt_number=200, wait_fixed=1000)
    def wait_for_all_executions(self, include_system_workflows=True):
        executions = self.client.executions.list(
            include_system_workflows=include_system_workflows,
            _all_tenants=True,
            _get_all_results=True
        )
        for execution in executions:
            if execution['status'] != 'terminated':
                raise Exception(
                    'Timed out: Execution {} did not terminate'.format(
                        execution['id'],
                    )
                )

    @only_manager
    @retrying.retry(stop_max_attempt_number=60, wait_fixed=5000)
    def wait_for_manager(self):
        self._logger.info('Checking for starter service')

        # If we don't wait for this then tests get a bit racier
        self.run_command(
            "systemctl status cloudify-starter 2>&1"
            "| grep -E '(status=0/SUCCESS)|(could not be found)'")
        # ...and apparently we're misnaming it at the moment
        self.run_command(
            "systemctl status cfy-starter 2>&1"
            "| grep -E '(status=0/SUCCESS)|(could not be found)'")

        self._logger.info('Checking manager status')
        try:
            manager_status = self.client.manager.get_status()
        except Exception as err:
            self._logger.info(str(err))
            if 'SSL must be used' in str(err):
                self._logger.info(
                    'Detected that SSL was required, '
                    'updating certs and client.')
                self.client = self.get_rest_client()
            raise

        if manager_status['status'] != HEALTHY_STATE:
            raise Exception(
                'Timed out: Manager services did not start successfully. '
                'Inactive services: {}'.format(
                    ', '.join(
                        str(item)
                        for item in manager_status['services'].values()
                        if item['status'] != 'Active'
                    )
                )
            )
        self._logger.info('Manager on %s is up', self.ip_address)

    @only_manager
    def get_rest_client(self, username=None, password=None, tenant=None,
                        proto='auto', download_ca=True):
        test_mgr_conf = self._test_config['test_manager']
        username = username or test_mgr_conf['username']
        password = (
            password
            or self.mgr_password
        )
        tenant = tenant or test_mgr_conf['tenant']

        if proto == 'auto':
            proto = 'http'
            ssl_check = requests.get(
                'http://{}/api/v3.1/status'.format(self.ip_address))
            self._logger.info('Rest client generation SSL check response: %s',
                              ssl_check.text)
            if 'SSL_REQUIRED' in ssl_check.text:
                proto = 'https'

        if proto == 'https' and download_ca:
            self.download_rest_ca()

        return util.create_rest_client(
            self.ip_address,
            username=username,
            password=password,
            tenant=tenant,
            cert=self.api_ca_path,
            protocol=proto,
        )

    @only_manager
    def download_rest_ca(self, force=False):
        self.api_ca_path = self._tmpdir / self.server_id + '_api.crt'
        if os.path.exists(self.api_ca_path):
            if force:
                os.unlink(self.api_ca_path)
            else:
                self._logger.info('Skipping rest CA download, already in %s',
                                  self.api_ca_path)
                return
        self._logger.info('Downloading rest CA to %s', self.api_ca_path)
        self.get_remote_file(
            '/etc/cloudify/ssl/cloudify_internal_ca_cert.pem',
            self.api_ca_path,
        )

    @only_manager
    def clean_local_rest_ca(self):
        if self.api_ca_path and os.path.exists(self.api_ca_path):
            self._logger.info('Removing local copy of manager CA.')
            os.unlink(self.api_ca_path)

    @only_manager
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
            NETMASK="255.255.255.0"
            DEFROUTE="no"
            MTU=1450
        """)

        self._logger.info('Adding extra NICs...')

        for i in range(0, len(self.networks)):
            network_file_path = self._tmpdir / 'network_cfg_{}'.format(i)
            ip_addr = self.networks['network_{}'.format(i + 1)]
            config_content = template.format(i, ip_addr)

            with open(network_file_path, 'w') as conf_handle:
                conf_handle.write(config_content)
            self.put_remote_file(
                '/etc/sysconfig/network-scripts/ifcfg-eth{0}'.format(i),
                network_file_path,
            )
            self.run_command('ifup eth{0}'.format(i), use_sudo=True)

    def _is_manager_image_type(self):
        if self.image_type == 'master':
            return True
        try:
            # If the name starts with a number, it's a manager version
            int(self.image_type[0])
            return True
        except Exception:
            return False

    def _is_rhel8_supported(self):
        if self.image_type == 'master':
            return True
        if parse_version(self.image_type) >= parse_version('6.4.0'):
            return True
        return False

    def _set_image_details(self):
        if self.is_manager:
            distro = self._test_config['test_manager']['distro']
            if distro == 'rhel-8' and not self._is_rhel8_supported():
                distro == 'rhel-7'

            username_key = 'centos_7' if distro == 'centos' else 'rhel_7'

            image_template = self._test_config['manager_image_names'][distro]

            if self.image_type in ('master', 'installer'):
                manager_version = self._test_config['testing_version']
            else:
                manager_version = self.image_type

            if self.bootstrappable:
                self.should_finalize = False
            else:
                self.restservice_expected = True

            self.image_name = util.substitute_testing_version(
                image_template,
                manager_version,
            ).replace('-ga', '')
        else:
            username_key = self.image_type

            image_names = {
                entry: img
                for entry, img in self._test_config.platform.items()
                if entry.endswith('_image')
            }
            image_name = self.image_type + '_image'

            if image_name not in image_names:
                raise ValueError(
                    '{img} is not a supported image. '
                    'Supported: {supported}'.format(
                        img=image_name,
                        supported=','.join(image_names),
                    )
                )
            self.image_name = image_names[image_name]

        if username_key.startswith('rhel') and not self.is_manager:
            self.username = (
                self._test_config.platform['rhel_username_override']
                or self._test_config['test_os_usernames'][username_key]
            )
        else:
            self.username = (
                self._test_config['test_os_usernames'][username_key]
            )

    def rsync_backup(self):
        self.wait_for_ssh()
        self._logger.info(
            'Creating Rsync backup for host {}. Might take up to 5 '
            'minutes...'.format(self.deployment_id))
        self.run_command("mkdir /cfy_backup", use_sudo=True)
        rsync_backup_file = self._tmpdir / 'rsync_backup_{0}'.format(
            self.ip_address)
        locations = ' '.join(RSYNC_LOCATIONS)
        backup_commands = (
            f'sudo rsync -aAHX {locations} /cfy_backup '
            '> /tmp/rsync_backup.log 2>&1 '
            '; res=$? '
            # An exit code of 24 means files vanished during copy. This is
            # something that will happen occasionally and we should not
            # treat it as a failure.
            '; [[ $res -eq 24 ]] && res=0 '
            '; [[ $res -eq 0 ]] && touch /tmp/rsync_backup_complete'
        )
        rsync_backup_file.write_text(
            "(" + backup_commands + ") "
            "|| touch /tmp/rsync_backup_failed &")
        self.put_remote_file('/tmp/rsync_backup_script', rsync_backup_file)
        self.run_command('nohup bash /tmp/rsync_backup_script &>/dev/null &')

    def rsync_restore(self):
        # Revert install config to avoid leaking state between tests
        if self.is_manager:
            self.install_config = copy.deepcopy(self.basic_install_config)
        if self.is_manager:
            self.stop_manager_services()
            self._logger.info('Cleaning profile/CA dir from home dir')
            self.run_command('rm -rf ~/.cloudify*')
            self._logger.info('Cleaning root cloudify profile')
            self.run_command('sudo rm -rf /root/.cloudify')
            self.clean_local_rest_ca()
        self._logger.info(
            'Restoring from an Rsync backup for host {}. Might take '
            'up to 1 minute...'.format(self.deployment_id))
        rsync_restore_file = self._tmpdir / 'rsync_restore_{0}'.format(
            self.ip_address)
        rsync_restore_file.write_text(
            "(sudo rsync -aAHX /cfy_backup/* / --delete "
            "> /tmp/rsync_restore.log 2>&1 "
            "&& touch /tmp/rsync_restore_complete) "
            "|| touch /tmp/rsync_restore_failed &")
        self.put_remote_file('/tmp/rsync_restore_script',
                             rsync_restore_file)
        self.run_command('nohup bash /tmp/rsync_restore_script '
                         '&>/dev/null &')

    def async_command_is_complete(self, process_name):
        unfriendly_name = process_name.replace(' ', '_').lower()
        result = self.run_command(
            'if [[ -f /tmp/{0}_complete ]]; then echo done; '
            'elif [[ -f /tmp/{0}_failed ]]; then echo failed; '
            'else echo not done; '
            'fi'.format(unfriendly_name)
        ).stdout.strip()
        if result == 'done':
            self._logger.info('{0} complete for host {1}!'
                              .format(process_name, self.deployment_id))
            return True
        elif result == 'failed':
            self._logger.error('{0} FAILED for host {1}!'
                               .format(process_name, self.deployment_id))
            self.run_command(f'cat /tmp/{unfriendly_name}.log',
                             warn_only=True)
            raise RuntimeError('{} failed.'.format(process_name))
        else:
            self._logger.info('Still performing {0} on host {1}...'
                              .format(process_name, self.deployment_id))
            return False


class Hosts(object):
    def __init__(self,
                 ssh_key,
                 tmpdir,
                 test_config,
                 logger,
                 request,
                 number_of_instances=1,
                 instances=None,
                 flavor=None,
                 multi_net=False,
                 bootstrappable=False,
                 vm_net_mappings=None,
                 ipv6_net=False):
        """
        instances: supply a list of VM instances.
        This allows pre-configuration to happen before starting the hosts, or
        for a list of instances of different versions to be created at once.
        if instances is provided, number_of_instances will be ignored
        """
        if sys.stdout.encoding.lower() != 'utf-8':
            raise RuntimeError(
                'Trying to run without IO encoding being set to utf-8 '
                'will occasionally result in errors. Current encoding is '
                '{current}. Please re-run, e.g. '
                'PYTHONIOENCODING=utf-8 {command}'.format(
                    current=sys.stdout.encoding,
                    command=' '.join(sys.argv),
                )
            )

        self._logger = logger
        self._test_config = test_config
        self._tmpdir = tmpdir
        self._ssh_key = ssh_key
        self.preconfigure_callback = None
        if instances is None:
            self.instances = [VM('master', test_config, bootstrappable)
                              for _ in range(number_of_instances)]
        else:
            self.instances = instances
        self._request = request
        self.tenant = None
        self.deployments = []
        self.blueprints = []
        self.test_identifier = None
        self._test_vm_installs = {}
        self._test_vm_uninstalls = {}
        self._platform_resource_ids = {}

        self.multi_net = multi_net
        self.vm_net_mappings = vm_net_mappings or {}
        self.ipv6_net = ipv6_net

        if self.ipv6_net:
            if self._test_config['target_platform'].lower() != 'aws':
                raise RuntimeError('Tests in the IPv6-enabled environments '
                                   'require AWS target platform.')
            if self.multi_net:
                raise RuntimeError('Cannot initialize both multi-net and '
                                   'IPv6-enabled infrastructure.')

        infra_mgr_config = self._test_config['infrastructure_manager']
        self._infra_client = util.create_rest_client(
            infra_mgr_config['address'],
            username='admin',
            password=infra_mgr_config['admin_password'],
            cert=infra_mgr_config['ca_cert'],
            protocol='https' if infra_mgr_config['ca_cert'] else 'http',
        )

        if flavor:
            self.server_flavor = flavor
        else:
            self.server_flavor = self._test_config.platform['linux_size']

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
                # cosmo_tester/test_suites/some_tests/\
                # some_test.py::test_specific_thing
                os.environ['PYTEST_CURRENT_TEST'].split('/')[-1],
            ),
            time=datetime.strftime(datetime.now(), '%Y%m%d%H%M%S'),
        )
        self.test_identifier = test_identifier

        try:
            self._logger.info('Creating test tenant')
            self._infra_client.tenants.create(test_identifier)
            self._infra_client._client.headers[
                CLOUDIFY_TENANT_HEADER] = test_identifier
            self.tenant = test_identifier

            self._upload_secrets_to_infrastructure_manager()
            self._upload_plugins_to_infrastructure_manager()
            self._upload_blueprints_to_infrastructure_manager()

            self._deploy_test_infrastructure(test_identifier)

            # Deploy hosts in parallel
            for index, instance in enumerate(self.instances):
                self._start_deploy_test_vm(instance.image_name, index,
                                           test_identifier,
                                           instance.is_manager)
            self._finish_deploy_test_vms()

            for instance in self.instances:
                if instance.is_manager and not instance.bootstrappable:
                    # A pre-bootstrapped manager is desired for this test,
                    # let's make it happen.
                    instance.bootstrap(
                        upload_license=self._test_config['premium'],
                        blocking=False)

            for instance in self.instances:
                if instance.is_manager and not instance.bootstrappable:
                    self._logger.info('Waiting for instance %s to bootstrap',
                                      instance.image_name)
                    while not instance.bootstrap_is_complete():
                        time.sleep(3)
                if instance.should_finalize:
                    instance.finalize_preparation()
        except Exception as err:
            self._logger.error(
                "Encountered exception trying to create test resources: %s.\n"
                "Attempting to tear down test resources.", str(err)
            )
            self.destroy()
            raise

    def destroy(self, passed=None):
        """Destroys the infrastructure. """
        if passed is None:
            try:
                passed = self._request.session.testspassed
            except AttributeError:
                passed = 0
        if passed:
            if self._test_config['teardown']['on_success']:
                self._logger.info('Preparing to destroy with passed tests...')
            else:
                self._logger.info(
                    'Tests passed, skipping teardown due to configuration.'
                    'To tear down, clean deployments on your test manager '
                    'under tenant {}'.format(self.test_identifier)
                )
                return
        else:
            if self._test_config['teardown']['on_failure']:
                self._logger.info('Preparing to destroy with failed tests...')
            else:
                self._logger.info(
                    'Tests failed, skipping teardown due to configuration. '
                    'To tear down, clean deployments on your test manager '
                    'under tenant {}'.format(self.test_identifier)
                )
                return

        self._logger.info('Destroying test hosts..')
        if self.tenant:
            self._logger.info('Ensuring executions are stopped.')
            cancelled = []
            execs = self._infra_client.executions.list()
            for execution in execs:
                if execution['workflow_id'] != (
                    'create_deployment_environment'
                ):
                    self._logger.info(
                        'Ensuring %s (%s) is not running.',
                        execution['id'],
                        execution['workflow_id'],
                    )
                    self._infra_client.executions.cancel(
                        execution['id'], force=True, kill=True
                    )
                    cancelled.append(execution['id'])
                else:
                    self._logger.info(
                        'Skipping %s (%s).',
                        execution['id'],
                        execution['workflow_id'],
                    )

            cancel_complete = []
            for execution_id in cancelled:
                self._logger.info('Checking {} is cancelled.'.format(
                    execution_id,
                ))
                for _ in range(30):
                    execution = self._infra_client.executions.get(
                        execution_id)
                    self._logger.info('{} is in state {}.'.format(
                        execution_id,
                        execution['status'],
                    ))
                    if execution['status'] == 'cancelled':
                        cancel_complete.append(execution_id)
                        break
                    else:
                        time.sleep(3)

            cancel_failures = set(cancelled).difference(cancel_complete)
            if cancel_failures:
                self._logger.error(
                    'Teardown failed due to the following executions not '
                    'entering the correct state after kill-cancel: {}'.format(
                        ', '.join(cancel_failures),
                    )
                )
                raise RuntimeError('Could not complete teardown.')

            self._start_undeploy_test_vms()
            self._finish_undeploy_test_vms()

            self._logger.info('Uninstalling infrastructure')
            util.run_blocking_execution(
                self._infra_client, 'infrastructure', 'uninstall',
                self._logger)
            util.delete_deployment(self._infra_client, 'infrastructure',
                                   self._logger)

            self._logger.info('Deleting blueprints.')
            for blueprint in self.blueprints:
                self._logger.info('Deleting %s', blueprint)
                self._infra_client.blueprints.delete(blueprint)

            self._logger.info('Deleting plugins.')
            plugins = self._infra_client.plugins.list()
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
                    self._infra_client.plugins.delete(plugin['id'])

            self._logger.info('Deleting tenant %s', self.tenant)
            self._infra_client._client.headers[
                CLOUDIFY_TENANT_HEADER] = 'default_tenant'
            self._infra_client.tenants.delete(self.tenant)
            self.tenant = None

    def rsync_backup(self):
        for instance in self.instances:
            instance.rsync_backup()
            self._logger.info('Waiting for instance %s to Rsync backup',
                              instance.image_name)
        for instance in self.instances:
            while not instance.async_command_is_complete('Rsync backup'):
                time.sleep(3)

    def _upload_secrets_to_infrastructure_manager(self):
        self._logger.info(
            'Uploading secrets to infrastructure manager.'
        )
        mappings = self._test_config.platform.get(
            'secrets_mapping', {})

        for secret_name, mapping in mappings.items():
            self._infra_client.secrets.create(
                secret_name, self._test_config.platform[mapping],
            )

        with open(self._ssh_key.public_key_path) as ssh_pubkey_handle:
            ssh_pubkey = ssh_pubkey_handle.read()
        self._infra_client.secrets.create(
            "ssh_public_key", ssh_pubkey,
        )

    def _upload_plugins_to_infrastructure_manager(self):
        plugin_details = self._test_config.platform
        current_plugins = self._infra_client.plugins.list(_all_tenants=True)
        if any(
            plugin["package_name"] == plugin_details['plugin_package_name']
            and re.match(r'{}'.format(plugin_details['plugin_version']),
                         plugin["package_version"])
            for plugin in current_plugins
        ):
            self._logger.info('Plugin already present.')
        else:
            raise RuntimeError(
                'The manager must have a plugin called {}. '
                'This should be uploaded with --visibility=global,'
                'and match version regex: {}'.format(
                    plugin_details['plugin_package_name'],
                    plugin_details['plugin_version'],
                )
            )

    def _upload_blueprints_to_infrastructure_manager(self):
        self._logger.info(
            'Uploading test blueprints to infrastructure manager.'
        )
        suffix = ''
        if self.ipv6_net:
            suffix = '{}-ipv6'.format(suffix)
        if self.multi_net:
            suffix = '{}-multi-net'.format(suffix)
        self._infra_client.blueprints.upload(
            util.get_resource_path(
                'infrastructure_blueprints/{}/infrastructure{}.yaml'.format(
                    self._test_config['target_platform'],
                    suffix,
                )
            ),
            "infrastructure",
            async_upload=True
        )
        util.wait_for_blueprint_upload(self._infra_client, "infrastructure")

        self.blueprints.append('infrastructure')
        test_vm_suffixes = ['']
        if self.ipv6_net:
            test_vm_suffixes.append('-ipv6')
        elif self.multi_net:
            test_vm_suffixes.append('-multi-net')

        for suffix in test_vm_suffixes:
            blueprint_id = "test_vm{}".format(suffix)
            self._infra_client.blueprints.upload(
                util.get_resource_path(
                    'infrastructure_blueprints/{}/vm{}.yaml'.format(
                        self._test_config['target_platform'],
                        suffix,
                    )
                ),
                blueprint_id,
                async_upload=True
            )
            util.wait_for_blueprint_upload(self._infra_client, blueprint_id)
            self.blueprints.append('test_vm{}'.format(suffix))

    def _deploy_test_infrastructure(self, test_identifier):
        self._logger.info('Creating test infrastructure inputs.')
        infrastructure_inputs = {'test_infrastructure_name': test_identifier}
        mappings = self._test_config.platform.get(
            'infrastructure_inputs_mapping', {})

        for blueprint_input, mapping in mappings.items():
            infrastructure_inputs[blueprint_input] = (
                self._test_config.platform[mapping]
            )

        # Written to disk to aid in troubleshooting
        infrastructure_inputs_path = self._tmpdir / 'infra_inputs.yaml'
        with open(infrastructure_inputs_path, 'w') as inp_handle:
            inp_handle.write(json.dumps(infrastructure_inputs))

        self._logger.info(
            'Creating test infrastructure using infrastructure manager.'
        )
        util.create_deployment(
            self._infra_client, 'infrastructure', 'infrastructure',
            self._logger, inputs=infrastructure_inputs,
        )
        self.deployments.append('infrastructure')
        util.run_blocking_execution(
            self._infra_client, "infrastructure", "install", self._logger)

        if self.multi_net:
            network_mappings = {}
            if self._test_config['target_platform'] == 'aws':
                cidr = 'CidrBlock'
            else:
                cidr = 'cidr'
            for sn in range(1, 4):
                subnet_details = self._infra_client.nodes.get(
                    deployment_id='infrastructure',
                    node_id='test_subnet_{}'.format(sn)
                )['properties']['resource_config']
                network_mappings['network_{}'.format(sn)] = ip_network(
                    # Has to be unicode for ipaddress library.
                    # Converting like this for py3 compat
                    u'{}'.format(subnet_details[cidr]),
                )
            self.network_mappings = network_mappings

        if self._test_config['target_platform'] == 'aws':
            self._populate_aws_platform_properties()

    def _start_deploy_test_vm(self, image_id, index, test_identifier,
                              is_manager):
        self._logger.info(
            'Preparing to deploy instance %d of image %s',
            index,
            image_id,
        )

        vm_id = 'vm_{}_{}'.format(
            image_id
            .replace(' ', '_')
            .replace('(', '_')
            .replace(')', '_')
            # Openstack drop the part that contains '.' when generate the name
            # This to replace '.' with '-'
            .replace('.', '-'),
            index,
        )

        self._logger.info('Creating test VM inputs for %s_%d',
                          image_id, index)
        vm_inputs = {
            'test_infrastructure_name': test_identifier,
            'userdata': self.instances[index].userdata,
            'flavor': self.server_flavor,
        }
        if self._test_config['target_platform'] == 'openstack':
            vm_inputs['floating_network_id'] = (
                self._test_config['openstack']['floating_network_id']
            )
            vm_inputs['image'] = image_id
        elif self._test_config['target_platform'] == 'aws':
            vm_inputs.update(self._platform_resource_ids)
            if self.multi_net:
                use_net = self.vm_net_mappings.get(index, 1)
                if use_net > 1:
                    key = 'subnet_{}_id'.format(use_net)
                else:
                    key = 'subnet_id'
                vm_inputs['subnet_id'] = self._platform_resource_ids[key]
            if is_manager:
                vm_inputs['name_filter'] = {
                    "Name": "tag:Name",
                    "Values": [image_id]
                }
                vm_inputs['image_owner'] = self._test_config['aws'][
                    'named_image_owners']
            else:
                vm_inputs['image_id'] = image_id

        blueprint_id = 'test_vm'
        if self.multi_net:
            if index in self.vm_net_mappings:
                vm_inputs['use_net'] = self.vm_net_mappings.get(index, 1)
                if self._test_config['target_platform'] == 'aws':
                    vm_inputs.pop('subnet_2_id')
                    vm_inputs.pop('subnet_3_id')
            else:
                blueprint_id = blueprint_id + '-multi-net'
        # Dumped to file to aid in troubleshooting
        vm_inputs_path = self._tmpdir / '{}_{}.yaml'.format(vm_id, index)
        with open(vm_inputs_path, 'w') as inp_handle:
            inp_handle.write(json.dumps(vm_inputs))

        self._logger.info('Deploying instance %d of %s', index, image_id)
        util.create_deployment(
            self._infra_client, blueprint_id, vm_id, self._logger,
            inputs=vm_inputs,
        )
        self.deployments.append(vm_id)
        self._test_vm_installs[vm_id] = (
            self._infra_client.executions.start(
                vm_id, 'install',
            ),
            index,
        )

    def _populate_aws_platform_properties(self):
        self._logger.info('Retrieving AWS resource IDs')
        resource_ids = {}

        subnet = util.get_node_instances(
            'test_subnet_1', 'infrastructure', self._infra_client)[0]
        resource_ids['subnet_id'] = subnet['runtime_properties'][
            'aws_resource_id']
        if self.multi_net:
            subnet_2 = util.get_node_instances(
                'test_subnet_2', 'infrastructure', self._infra_client)[0]
            resource_ids['subnet_2_id'] = subnet_2['runtime_properties'][
                'aws_resource_id']
            subnet_3 = util.get_node_instances(
                'test_subnet_3', 'infrastructure', self._infra_client)[0]
            resource_ids['subnet_3_id'] = subnet_3['runtime_properties'][
                'aws_resource_id']

        vpc = util.get_node_instances(
            'vpc', 'infrastructure', self._infra_client)[0]
        resource_ids['vpc_id'] = vpc['runtime_properties']['aws_resource_id']
        security_group = util.get_node_instances(
            'security_group', 'infrastructure', self._infra_client)[0]
        resource_ids['security_group_id'] = security_group[
            'runtime_properties']['aws_resource_id']

        self._platform_resource_ids = resource_ids

    def _finish_deploy_test_vms(self):
        node_instances = {}
        for vm_id, details in self._test_vm_installs.items():
            execution, index = details
            util.wait_for_execution(self._infra_client, execution,
                                    self._logger)

            self._logger.info('Retrieving deployed instance details.')
            node_instance = util.get_node_instances('test_host', vm_id,
                                                    self._infra_client)[0]

            self._logger.info('Storing instance details.')
            self._update_instance(
                index,
                node_instance,
            )

            node_instances[index] = node_instance

        if self.ipv6_net:
            self._disable_ipv4(node_instances)

    def _start_undeploy_test_vms(self):
        # Operate on all deployments except the infrastructure one
        for vm_id in self.deployments[1:]:
            self._logger.info('Uninstalling %s', vm_id)
            self._test_vm_uninstalls[vm_id] = (
                self._infra_client.executions.start(
                    vm_id, 'uninstall',
                )
            )

    def _finish_undeploy_test_vms(self):
        for vm_id, execution in self._test_vm_uninstalls.items():
            util.wait_for_execution(self._infra_client, execution,
                                    self._logger)
        # Do this separately to cope with large deployment counts and small
        # mgmtworker worker counts
        for vm_id, execution in self._test_vm_uninstalls.items():
            util.delete_deployment(self._infra_client, vm_id,
                                   self._logger)

    def _update_instance(self, server_index, node_instance):
        instance = self.instances[server_index]
        runtime_props = node_instance['runtime_properties']

        public_ip_address = runtime_props['public_ip_address']
        private_ip_address = runtime_props['ipv6_address'] if self.ipv6_net \
            else runtime_props['ip']

        node_instance_id = node_instance['id']
        deployment_id = node_instance['deployment_id']
        id_key = 'id'
        if self._test_config['target_platform'] == 'aws':
            id_key = 'aws_resource_id'
        server_id = runtime_props[id_key]

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

        instance.assign(
            public_ip_address,
            private_ip_address,
            networks,
            self._ssh_key,
            self._logger,
            self._tmpdir,
            node_instance_id,
            deployment_id,
            server_id,
            server_index,
        )

    def _disable_ipv4(self, node_instances):
        self._logger.info('Disabling IPv4 on private interfaces.')
        # This code needs to be run when all of the cluster VMs are already set
        # up and running.  This is because we must know IP addresses of all of
        # the nodes in order to disable IPv4 communication across the cluster.
        for server_index, node_instance in node_instances.items():
            instance = self.instances[server_index]

            instance.wait_for_ssh()

            for ip in [ni['runtime_properties']['ip']
                       for i, ni in node_instances.items()
                       if i != server_index]:
                self._logger.info(
                    'Poisoning ARP to disable IPv4 communication {0}->{1}.'
                    .format(node_instance['runtime_properties']['ip'], ip))

                instance.run_command('sudo arp -s {0} de:ad:be:ef:ca:fe'
                                     .format(ip))
