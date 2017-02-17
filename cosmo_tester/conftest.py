
import logging
import json
import os
import shutil
import sys
import tempfile
import uuid

from fabric import api as fabric_api
from fabric import context_managers as fabric_context_managers
from path import Path
import pytest
import sh
import yaml

import cosmo_tester
from cosmo_tester.framework import util


class AttributesDict(dict):
    __getattr__ = dict.__getitem__


class CloudifyManager(object):

    def __init__(self, ip_address, ssh_user, local_ssh_key, username, password, tenant):
        self.ip_address = ip_address
        self.ssh_user = ssh_user
        self.local_ssh_key = local_ssh_key
        self.username = username
        self.password = password
        self.tenant = tenant
        self.remote_private_key_path = '/etc/cloudify/key.pem'
        self.remote_openstack_config_path = '/root/openstack_config.json'
        self.client = self._create_rest_client()

    def _create_rest_client(self):
        return util.create_rest_client(
                self.ip_address,
                username=self.username,
                password=self.password,
                tenant=self.tenant)


class SSHKey(object):

    def __init__(self, private_key_path, public_key_path):
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path


@pytest.fixture(scope='class')
def cfy(request):
    cfy = util.sh_bake(sh.cfy)
    if request.cls:
        request.cls.cfy = cfy
    return cfy


@pytest.fixture(scope='class')
def attributes(request, logger):
    attributes_file = util.get_resource_path('attributes.yaml')
    logger.info('Loading attributes from: %s', attributes_file)
    with open(attributes_file, 'r') as f:
        attrs = AttributesDict(yaml.load(f))
        if request.cls:
            request.cls.attributes = attrs
        return attrs


@pytest.fixture(scope='class')
def logger(request):
    logger = logging.getLogger('test-logger')
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter(fmt='%(asctime)s [%(levelname)s] '
                                      '[%(name)s] %(message)s',
                                  datefmt='%H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    if request.cls:
        request.cls.logger = logger
    return logger


@pytest.fixture(scope='class')
def class_tmpdir(request, logger):
    if request.cls:
        suffix = request.cls.__name__
    else:
        suffix = request.module.__name__
    temp_dir = Path(tempfile.mkdtemp(suffix=suffix))
    logger.info('Created temp folder: %s', temp_dir)

    if request.cls:
        request.cls.tmpdir = temp_dir

    yield temp_dir

    logger.info('Deleting temp folder: %s', temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture(scope='class')
def ssh_key(request, class_tmpdir, logger):
    private_key_path = class_tmpdir / 'key.pem'
    public_key_path = class_tmpdir / 'key.pem.pub'
    logger.info('Creating temporary SSH keys at: %s', class_tmpdir)
    if os.system("ssh-keygen -t rsa -f {} -q -N ''".format(
            private_key_path)) != 0:
        raise IOError('Error creating SSH key: {}'.format(private_key_path))
    if os.system('chmod 400 {}'.format(private_key_path)) != 0:
        raise IOError('Error setting private key file permission')

    yield SSHKey(private_key_path, public_key_path)

    public_key_path.remove()
    private_key_path.remove()


def upload_openstack_plugin_to_manager(rest_client, logger):
    plugins_list = util.get_plugin_wagon_urls()
    openstack_plugin_wagon = [
        x['wgn_url'] for x in plugins_list
        if x['name'] == 'openstack_centos_core']
    if len(openstack_plugin_wagon) != 1:
        logger.error(
                'OpenStack plugin wagon not found in:%s%s',
                os.linesep, json.dumps(plugins_list, indent=2))
        raise RuntimeError('OpenStack plugin not found in wagons list')
    logger.info('Uploading openstack plugin to manager.. [%s]',
                openstack_plugin_wagon[0])
    rest_client.plugins.upload(openstack_plugin_wagon[0])


# TODO: create a context manager on CloudifyManager class for running fabric commands
def upload_necessary_files_to_manager(manager, openstack_config_file, logger):
    logger.info('Uploading necessary files to manager..')
    with fabric_context_managers.settings(
            host_string=manager.ip_address,
            user=manager.ssh_user,
            key_filename=manager.local_ssh_key.private_key_path,
            connections_attempts=3,
            abort_on_prompts=True):
        fabric_api.put(openstack_config_file,
                       manager.remote_openstack_config_path,
                       use_sudo=True)
        fabric_api.put(manager.local_ssh_key.private_key_path,
                       manager.remote_private_key_path,
                       use_sudo=True)


@pytest.fixture(scope='class')
def manager(request, cfy, ssh_key, class_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    logger.info('Creating cloudify manager from image..')

    openstack_config_file = class_tmpdir / 'openstack_config.json'
    openstack_config_file.write_text(json.dumps({
        'username': os.environ['OS_USERNAME'],
        'password': os.environ['OS_PASSWORD'],
        'tenant_name': os.environ['OS_TENANT_NAME'],
        'auth_url': os.environ['OS_AUTH_URL']
    }, indent=2))

    terraform_template_file = class_tmpdir / 'openstack-vm.tf'

    shutil.copy(util.get_resource_path('terraform/openstack-vm.tf'),
                terraform_template_file)

    terraform = util.sh_bake(sh.terraform)
    terraform_inputs_file = class_tmpdir / 'terraform-vars.json'
    terraform_inputs_file.write_text(json.dumps({
        'resource_suffix': str(uuid.uuid4()),
        'public_key_path': ssh_key.public_key_path,
        'private_key_path': ssh_key.private_key_path,
        'flavor': attributes.large_flavor_name,
        'image': attributes.cloudify_manager_image_name,
    }, indent=2))

    try:
        with class_tmpdir:
            terraform.apply(['-var-file', terraform_inputs_file])
            outputs = AttributesDict({k: v['value'] for k, v in json.loads(
                    terraform.output(['-json']).stdout).items()})
        attributes.update(outputs)
        manager = CloudifyManager(outputs.public_ip_address,
                                  attributes.centos7_username,
                                  ssh_key,
                                  attributes.cloudify_username,
                                  attributes.cloudify_password,
                                  attributes.cloudify_tenant)
        cfy.profiles.use('{0} -u {1} -p {2} -t {3}'.format(
                manager.ip_address,
                attributes.cloudify_username,
                attributes.cloudify_password,
                attributes.cloudify_tenant).split())

    except sh.ErrorReturnCode as e:
        logger.error('Error creating cloudify manager from image: %s', e)
        try:
            with class_tmpdir:
                terraform.destroy(
                    ['-var-file', terraform_inputs_file, '-force'])
        except sh.ErrorReturnCode as ex:
            logger.error('Error on terraform destroy: %s', ex)
        raise

    upload_necessary_files_to_manager(manager, openstack_config_file, logger)
    upload_openstack_plugin_to_manager(manager.client, logger)

    if request.cls:
        request.cls.manager = manager

    yield manager

    logger.info('Destroying cloudify manager..')
    with class_tmpdir:
        terraform.destroy(['-var-file', terraform_inputs_file, '-force'])


