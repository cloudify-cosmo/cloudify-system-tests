from abc import ABCMeta, abstractmethod
import json
import os
import string

import retrying
import yaml

from cloudify_cli.constants import DEFAULT_TENANT_NAME

from cosmo_tester.framework import util

REGISTERED = {}
MANAGER_TYPES = set([
    '3.4.2',
    '4.0',
    '4.0.1',
    '4.1',
    '4.2',
    'master',
])
NON_MANAGER_TYPES = set([
    'centos',
])
REQUIRED_TYPES = MANAGER_TYPES.union(NON_MANAGER_TYPES)


class AutoRegister(ABCMeta):
    def __new__(meta, name, bases, class_dict):
        # Automatically register this class when it is defined
        cls = super(AutoRegister, meta).__new__(meta, name, bases, class_dict)
        register_class(cls)
        return cls


class BaseVM(object):
    __metaclass__ = AutoRegister

    @abstractmethod
    def create(self, *args, **kwargs):
        pass

    @abstractmethod
    def ssh(self, *args, **kwargs):
        pass

    @abstractmethod
    def __str__(self, *args, **kwargs):
        # This allows for nicer logging
        pass

    @abstractmethod
    def delete(self, *args, **kwargs):
        pass

    @abstractmethod
    def upload_necessary_files(self, *args, **kwargs):
        pass


class BaseManager(object):
    branch_name = 'master'

    @retrying.retry(stop_max_attempt_number=6*10, wait_fixed=10000)
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
                if (
                    instance['Id'] == 'cloudify-stage.service'
                    and not util.is_community()
                ):
                    assert instance['SubState'] == 'running', \
                        'service {0} is in {1} state'.format(
                                service['display_name'], instance['SubState'])

    @retrying.retry(stop_max_attempt_number=3, wait_fixed=3000)
    def use(self, tenant=None, profile_name=None):
        kwargs = {}
        if profile_name is not None:
            kwargs['profile_name'] = profile_name
        self._cfy.profiles.use([
            self.ip_address,
            '-u', self._attributes.cloudify_username,
            '-p', self._attributes.cloudify_password,
            '-t', tenant or self._attributes.cloudify_tenant,
            ], **kwargs)

    def upload_plugin(self, plugin_name, tenant_name=DEFAULT_TENANT_NAME):
        plugins_list = util.get_plugin_wagon_urls()
        plugin_wagon = [
            x['wgn_url'] for x in plugins_list
            if x['name'] == plugin_name]
        if len(plugin_wagon) != 1:
            self._logger.error(
                    '%s plugin wagon not found in:%s%s',
                    plugin_name,
                    os.linesep,
                    json.dumps(plugins_list, indent=2))
            raise RuntimeError(
                    '{} plugin not found in wagons list'.format(plugin_name))
        self._logger.info('Uploading %s plugin [%s] to %s..',
                          plugin_name,
                          plugin_wagon[0],
                          self)

        try:
            with self.ssh() as fabric_ssh:
                # This will only work for images as cfy is pre-installed there.
                # from some reason this method is usually less error prone.
                fabric_ssh.run(
                    'cfy plugins upload {0} -t {1}'.format(
                        plugin_wagon[0], tenant_name
                    ))
        except Exception:
            try:
                self.use()
                self._cfy.plugins.upload([plugin_wagon[0], '-t', tenant_name])
            except Exception:
                # This is needed for 3.4 managers. local cfy isn't
                # compatible and cfy isn't installed in the image
                self.client.plugins.upload(plugin_wagon[0])

    def teardown(self):
        with self.ssh() as fabric_ssh:
            fabric_ssh.run('cfy_manager remove --force')
            fabric_ssh.sudo('yum remove -y cloudify-manager-install')

    def _create_config_file(self):
        config_file = self._tmpdir / 'config_{0}.yaml'.format(self.index)
        install_config = {
            'manager':
                {
                    'public_ip': self.ip_address,
                    'private_ip': self.private_ip_address,
                    'security': {
                        'admin_username': self._attributes.cloudify_username,
                        'admin_password': self._attributes.cloudify_password,
                    }
                }
        }

        # Add any additional bootstrap inputs passed from the test
        install_config.update(self.additional_install_config)
        install_config_str = yaml.dump(install_config)

        self._logger.info(
            'Install config:\n{0}'.format(install_config_str))
        config_file.write_text(install_config_str)
        return config_file

    def bootstrap(self):
        manager_install_rpm = util.get_manager_install_rpm_url()
        install_config = self._create_config_file()
        install_rpm_file = 'cloudify-manager-install.rpm'
        with self.ssh() as fabric_ssh:
            fabric_ssh.run(
                'curl -sS {0} -o {1}'.format(
                    manager_install_rpm,
                    install_rpm_file
                )
            )
            fabric_ssh.sudo('yum install -y {0}'.format(install_rpm_file))
            fabric_ssh.put(
                install_config,
                '/opt/cloudify/config.yaml'
            )
            fabric_ssh.run('cfy_manager install')
        self.use()

    # The MTU is set to 1450 because we're using a static BOOTPROTO here (as
    # opposed to DHCP), which sets a lower default by default
    NETWORK_CONFIG_TEMPLATE = """DEVICE="eth{0}"
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
"""

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


class BackendDefinitionError(Exception):
    pass


def validate_backends():
    # Make sure each backend contains all the types it needs.
    for backend_name, backend in REGISTERED.items():
        backend_types = set(backend.keys())
        missing = REQUIRED_TYPES.difference(backend_types)
        if missing:
            raise BackendDefinitionError(
                'Backends must have {types} defined, but {backend_name} was '
                'missing: {missing}'.format(
                    types=', '.join(sorted(REQUIRED_TYPES)),
                    backend_name=backend_name,
                    missing=', '.join(sorted(missing))
                )
            )


def register_class(target_class):
    # Get the module name, e.g. openstack_terraform- this will be the same as
    # the file name of the backend, without the .py extension.
    backend_name = target_class.__module__.split('.')[-1]
    component = target_class.__name__

    if backend_name != 'base':
        # We only register classes that aren't in our base definitions
        if backend_name not in REGISTERED:
            REGISTERED[backend_name] = {}

        REGISTERED[backend_name][component] = target_class


def _normalise_manager_class_name(version_string):
    """
        Make a valid class name for a cloudify manager subclass based on the
        provided version.
    """
    base_name = 'Cloudify{version}Manager'
    allowed_characters = string.letters + string.digits + '_'
    version = ''.join((char if char in allowed_characters else '_'
                       for char in version_string))
    return base_name.format(version=version)


def generate_manager_types(Manager=BaseManager, VM=BaseVM):
    """
        Generate new classes with a class name based on the manager version.
        The branch name will be set so that the appropriate image will be used.
        A dict of classes will be returned, keyed on manager versions.
    """
    return {
        manager_type: type(
            _normalise_manager_class_name(manager_type),
            (Manager, VM),
            {
                'branch_name': manager_type,
            },
        )
        for manager_type in MANAGER_TYPES
    }
