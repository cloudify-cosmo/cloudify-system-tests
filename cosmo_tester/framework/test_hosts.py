from contextlib import contextmanager
import copy
from datetime import datetime
import functools
import hashlib
import json
import os
import re
import socket
import subprocess
import time
import uuid
import yaml

from fabric import Connection
from ipaddress import ip_address, ip_network
from paramiko.ssh_exception import NoValidConnectionsError, SSHException
import retrying
import textwrap
import winrm

from cloudify_rest_client.exceptions import CloudifyClientError

from cosmo_tester.framework import util
from cosmo_tester.framework.constants import CLOUDIFY_TENANT_HEADER

HEALTHY_STATE = 'OK'


def only_manager(func):
    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        if not self.is_manager:
            raise RuntimeError('This is not a manager')
        return func(self, *args, **kwargs)
    return wrapped


class VM(object):
    def __init__(self, image_type, test_config, bootstrappable=False):
        self.image_name = None
        self.userdata = ""
        self.username = None
        self.password = None
        self.enable_ssh_wait = True
        self.should_finalize = True
        self.restservice_expected = False
        self._test_config = test_config
        self.windows = 'windows' in image_type
        self._ssh_script_path = None
        self._tmpdir_base = None
        self.api_version = None
        self.bootstrappable = bootstrappable
        self.image_type = image_type
        self.is_manager = self._is_manager_image_type()
        self._set_image_details()

    def assign(
            self,
            public_ip_address,
            private_ip_address,
            networks,
            rest_client,
            ssh_key,
            logger,
            tmpdir,
            node_instance_id,
            deployment_id,
            server_id,
    ):
        self.ip_address = public_ip_address
        self.private_ip_address = private_ip_address
        self.client = rest_client
        self._ssh_key = ssh_key
        self._logger = logger
        self._tmpdir_base = tmpdir
        self._tmpdir = os.path.join(tmpdir, public_ip_address)
        os.makedirs(self._tmpdir)
        self.node_instance_id = node_instance_id
        self.deployment_id = deployment_id
        self.server_id = server_id
        # For backwards compatabilitish, keeping defaults here
        self.image_name = (
            self.image_name or self._test_config.platform['centos_7_image']
        )
        self.username = (
            self.username or self._test_config['test_os_usernames']['centos_7']
        )
        self._create_ssh_script()
        if self.is_manager:
            self.networks = networks
            self.basic_install_config = {
                'manager': {
                    'public_ip': str(public_ip_address),
                    'private_ip': str(private_ip_address),
                    'hostname': str(server_id),
                    'security': {
                        'admin_username': self._test_config[
                            'test_manager']['username'],
                        'admin_password': self._test_config[
                            'test_manager']['password'],
                    },
                },
            }
            self.install_config = copy.deepcopy(self.basic_install_config)
            self.api_version = 'v3.1'
        if self.windows:
            self.prepare_for_windows()

    def _create_ssh_script(self):
        self._ssh_script_path = self._tmpdir_base / 'ssh_{}'.format(
            self.server_id)
        ssh_script_content = (
            'ssh-keygen -R "{pub_ip}"\n'
            'ssh -i {key} -o StrictHostKeyChecking=no {user}@{pub_ip}\n'
        ).format(
            key=self._ssh_key.private_key_path,
            user=self.username,
            pub_ip=self.ip_address
        )
        with open(self._ssh_script_path, 'w') as fh:
            fh.write(ssh_script_content)
        subprocess.check_call(['chmod', '+x', self._ssh_script_path])

    def prepare_for_windows(self):
        """Prepare this VM to be created as a windows VM."""
        if self._ssh_script_path:
            subprocess.check_call('rm -f {}'.format(self._ssh_script_path))

        add_firewall_cmd = "&netsh advfirewall firewall add rule"
        password = 'AbCdEfG123456!'

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
            self.run_windows_command('Write-Output "Testing winrm."',
                                     powershell=True)
        except Exception as err:
            self._logger.warn('...failed: {err}'.format(err=err))
            raise
        self._logger.info('...Windows VM is up.')

    def run_windows_command(self, command, powershell=False,
                            warn_only=False):
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

    def get_windows_remote_file_content(self, path):
        return self.run_windows_command(
            'Get-Content -Path {}'.format(path),
            powershell=True).std_out

    def put_windows_remote_file_content(self, path, content):
        self.run_windows_command(
            "Add-Content -Path {} -Value '{}'".format(
                path,
                # Single quoted string will not be interpreted
                # But single quotes must be represented in such a string with
                # double single quotes
                content.replace("'", "''"),
            ),
            powershell=True,
        )

    @retrying.retry(stop_max_attempt_number=60, wait_fixed=3000)
    def wait_for_ssh(self):
        if self.enable_ssh_wait:
            with self.ssh() as conn:
                conn.run("echo SSH is up for {}".format(self.ip_address))

    @property
    def private_key_path(self):
        return self._ssh_key.private_key_path

    @contextmanager
    def ssh(self):
        conn = Connection(
            host=self.ip_address,
            user=self.username,
            connect_kwargs={
                'key_filename': [self.private_key_path],
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
                self.run_command('echo Still up...')
                time.sleep(3)
            except (SSHException, socket.timeout):
                # Errors like 'Connection reset by peer' can occur during the
                # shutdown, but we should wait a little longer to give other
                # services time to stop
                time.sleep(3)
                continue
            except NoValidConnectionsError:
                # By this point everything should be down.
                self._logger.info('Server stopped.')
                break

    def finalize_preparation(self):
        """Complete preparations for using a new instance."""
        self._logger.info('Finalizing server preparations.')
        self.wait_for_ssh()
        if self.restservice_expected:
            self._logger.info('Checking rest service.')
            self.wait_for_manager()
            self._logger.info('Applying license.')
            self.apply_license()

    @property
    def ssh_key(self):
        return self._ssh_key

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

        with self.ssh() as fabric_ssh:
            fabric_ssh.get(
                remote_tmp,
                local_path,
            )

    def put_remote_file(self, remote_path, local_path):
        """ Dump the contents of the local file into the remote path """

        remote_tmp = '/tmp/' + hashlib.sha1(
            remote_path.encode('utf-8')).hexdigest()
        self.run_command(
            'rm -rf {}'.format(remote_tmp),
            use_sudo=True,
        )
        with self.ssh() as fabric_ssh:
            # Similar to the way fabric1 did it
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

    def run_command(self, command, use_sudo=False, warn_only=False,
                    hide_stdout=False):
        hide = 'stdout' if hide_stdout else None
        with self.ssh() as fabric_ssh:
            if use_sudo:
                return fabric_ssh.sudo(command, warn=warn_only, hide=hide)
            else:
                return fabric_ssh.run(command, warn=warn_only, hide=hide)

    @only_manager
    def upload_test_plugin(self, tenant_name='default_tenant'):
        self._logger.info('Uploading test plugin to %s', tenant_name)
        with util.set_client_tenant(self.client, tenant_name):
            try:
                self.client.plugins.upload(
                    util.get_resource_path(
                        'plugin/test_plugin-1.0.0-py27-none-any.zip'
                    ),
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

        with self.ssh() as fabric_ssh:
            # the manager-ip-setter script creates the `touched` file when it
            # is done.
            try:
                # will fail on bootstrap based managers
                fabric_ssh.run('supervisorctl -a | grep manager-ip-setter')
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

    @only_manager
    def get_installed_paths_list(self):
        """Gtting the installed services' files paths.

        This function returns a list of the files that are created in case
        the installation was successful.
        We use the `main_services` to make sure we don't include the
        `monitoring_service` and `entropy_service`.
        """
        prefix = '/etc/cloudify/.installed/'
        main_services = [
            'database_service', 'queue_service', 'manager_service']
        services_to_install = self.install_config.get('services_to_install')

        return ([prefix + service for service in services_to_install
                 if service in main_services]
                if services_to_install else
                [prefix + service for service in main_services])

    @only_manager
    def teardown(self):
        with self.ssh() as fabric_ssh:
            fabric_ssh.run('cfy_manager remove --force')

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
    def bootstrap(self, upload_license=False,
                  blocking=True, restservice_expected=True, config_name=None):
        self.wait_for_ssh()
        self.restservice_expected = restservice_expected
        install_config = self._create_config_file(
            upload_license and self._test_config['premium'])
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

            if config_name:
                dest_config_path = \
                    '/etc/cloudify/{0}_config.yaml'.format(config_name)
                commands = [
                    'sudo mv /tmp/cloudify.conf {0}'.format(dest_config_path),
                    'cfy_manager install -c {0} > '
                    '/tmp/bs_logs/3_install 2>&1'.format(dest_config_path)
                ]
            else:
                commands = [
                    'sudo mv /tmp/cloudify.conf /etc/cloudify/config.yaml',
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

            fabric_ssh.run('nohup bash /tmp/bootstrap_script &>/dev/null &')

        if blocking:
            while True:
                if self.bootstrap_is_complete():
                    break
                else:
                    time.sleep(5)

    @only_manager
    def bootstrap_is_complete(self):
        with self.ssh() as fabric_ssh:
            # Using a bash construct because fabric seems to change its mind
            # about how non-zero exit codes should be handled frequently
            check_paths = (' || '.join('-f {}'.format(path) for path in
                                       self.get_installed_paths_list()))
            result = fabric_ssh.run(
                'if [[ {check_paths} ]]; then'
                '  echo done; '
                'elif [[ -f /tmp/bootstrap_failed ]]; then '
                '  echo failed; '
                'else '
                '  echo not done; '
                'fi'.format(check_paths=check_paths)
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
    def _update_aio_certs(self):
        key_path = '~/.cloudify-test-ca/' + self.private_ip_address + '.key'
        cert_path = '~/.cloudify-test-ca/' + self.private_ip_address + '.crt'
        ca_cert_path = '~/.cloudify-test-ca/ca.crt'

        with self.ssh() as ssh:
            self._logger.info('Making sure blackbox_exporter is running '
                              '(if applicable)')
            # Because the cert replacement tries to restart it, and sometimes
            # it isn't running which gets us stuck in a really slow and boring
            # loop.
            ssh.run('sudo supervisorctl start blackbox_exporter || true')

            self._logger.info('Generating certificates including public IP')
            ssh.run('cfy_manager generate-test-cert'
                    ' -s {0},{1}'.format(self.private_ip_address,
                                         self.ip_address))
            ssh.run('mkdir -p /tmp/new_cloudify_certs')
            new_cert_path = '/tmp/new_cloudify_certs/new_{}.pem'
            for purpose in [
                'internal', 'rabbitmq', 'postgresql_server', 'external',
            ]:
                self._logger.info('Preparing %s certificates', purpose)
                cert_dest = new_cert_path.format('_'.join([purpose, 'cert']))
                key_dest = new_cert_path.format('_'.join([purpose, 'key']))
                ca_dest = new_cert_path.format('_'.join([purpose, 'ca_cert']))
                if purpose == 'internal':
                    ca_dest = new_cert_path.format('ca_cert')
                for src, dest in [
                    (cert_path, cert_dest),
                    (key_path, key_dest),
                    (ca_cert_path, ca_dest),
                ]:
                    ssh.run('sudo cp {src} {dest}'.format(src=src, dest=dest))
            self._logger.info('Replacing certificates')
            ssh.run('cfy_manager certificates replace')

    @only_manager
    @retrying.retry(stop_max_attempt_number=90, wait_fixed=1000)
    def wait_for_manager(self):
        with self.ssh() as fabric_ssh:
            # If we don't wait for this then tests get a bit racier
            fabric_ssh.run(
                "systemctl status cloudify-starter 2>&1"
                "| grep -E '(status=0/SUCCESS)|(could not be found)'")

        try:
            manager_status = self.client.manager.get_status()
        except Exception as err:
            self._logger.info(str(err))
            if 'SSL must be used' in str(err):
                self._logger.info(
                    'Detected that SSL was required, '
                    'updating certs and client.')
                self._update_aio_certs()
                self.get_remote_file(
                    '/etc/cloudify/ssl/cloudify_internal_ca_cert.pem',
                    self._tmpdir / self.server_id + '_api.crt'
                )
                test_mgr_conf = self._test_config['test_manager']
                self.client = util.create_rest_client(
                    self.ip_address,
                    username=test_mgr_conf['username'],
                    password=test_mgr_conf['password'],
                    tenant=test_mgr_conf['tenant'],
                    cert=self._tmpdir / self.server_id + '_api.crt',
                    protocol='https',
                    api_version=self.api_version,
                )
            raise

        if manager_status['status'] != HEALTHY_STATE:
            raise Exception(
                'Timed out: Manager services did not start successfully. '
                'Inactive services: {}'.format(
                    ', '.join(
                        item['extra_info']['systemd']['unit_id']
                        for item in manager_status['services'].values()
                        if item['status'] != 'Active'
                    )
                )
            )

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
            NETMASK="255.255.255.128"
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

    def _set_image_details(self):
        if self.is_manager:
            distro = self._test_config['test_manager']['distro']
            image_names = self._test_config[
                'manager_image_names_{}'.format(distro)]
            image_name = self.image_type.replace('.', '_')
            if self.bootstrappable:
                if self.image_type == 'master':
                    image_name = 'installer'
                else:
                    image_name += '_installer'
                self.should_finalize = False
            else:
                self.restservice_expected = True

            username_key = 'centos_7' if distro == 'centos' else 'rhel_7'
        else:
            image_names = {
                entry: img
                for entry, img in self._test_config.platform.items()
                if entry.endswith('_image')
            }
            image_name = self.image_type + '_image'
            username_key = self.image_type
        if image_name not in image_names:
            raise ValueError(
                '{img} is not a supported image. '
                'Supported: {supported}'.format(
                    img=image_name,
                    supported=','.join(image_names),
                )
            )
        self.username = self._test_config['test_os_usernames'][username_key]
        self.image_name = image_names[image_name]


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
                 vm_net_mappings=None):
        """
        instances: supply a list of VM instances.
        This allows pre-configuration to happen before starting the hosts, or
        for a list of instances of different versions to be created at once.
        if instances is provided, number_of_instances will be ignored
        """
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

        infra_mgr_config = self._test_config['infrastructure_manager']
        self._infra_client = util.create_rest_client(
            infra_mgr_config['address'],
            username='admin',
            password=infra_mgr_config['admin_password'],
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
            self._logger.info('Openstack plugin already present.')
        else:
            raise RuntimeError(
                'The manager must have a plugin called {}. '
                'This should be uploaded with --visibility=global.'.format(
                    plugin_details['plugin_package_name'],
                )
            )

    def _upload_blueprints_to_infrastructure_manager(self):
        self._logger.info(
            'Uploading test blueprints to infrastructure manager.'
        )
        suffix = '-multi-net' if self.multi_net else ""
        self._infra_client.blueprints.upload(
            util.get_resource_path(
                'infrastructure_blueprints/{}/infrastructure{}.yaml'.format(
                    self._test_config['target_platform'],
                    suffix,
                )
            ),
            "infrastructure",
        )
        self.blueprints.append('infrastructure')
        test_vm_suffixes = ['']
        if self.multi_net:
            test_vm_suffixes.append('-multi-net')

        for suffix in test_vm_suffixes:
            self._infra_client.blueprints.upload(
                util.get_resource_path(
                    'infrastructure_blueprints/{}/vm{}.yaml'.format(
                        self._test_config['target_platform'],
                        suffix,
                    )
                ),
                "test_vm{}".format(suffix),
            )
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
        for vm_id, details in self._test_vm_installs.items():
            execution, index = details
            util.wait_for_execution(self._infra_client, execution,
                                    self._logger)

            self._logger.info('Retrieving deployed instance details.')
            node_instance = util.get_node_instances('test_host', vm_id,
                                                    self._infra_client)[0]

            self._logger.info('Storing instance details.')
            self._update_instance(
                self.instances[index],
                node_instance,
            )

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
            util.delete_deployment(self._infra_client, vm_id,
                                   self._logger)

    def _update_instance(self, instance, node_instance):
        runtime_props = node_instance['runtime_properties']

        public_ip_address = runtime_props['public_ip_address']
        private_ip_address = runtime_props['ip']

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

        if hasattr(instance, 'api_version'):
            test_mgr_conf = self._test_config['test_manager']
            rest_client = util.create_rest_client(
                public_ip_address,
                username=test_mgr_conf['username'],
                password=test_mgr_conf['password'],
                tenant=test_mgr_conf['tenant'],
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
            self._logger,
            self._tmpdir,
            node_instance_id,
            deployment_id,
            server_id,
        )
