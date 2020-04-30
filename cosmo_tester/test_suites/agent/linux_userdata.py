import os
import time

from cloudify import constants
from cloudify.compute import create_multi_mimetype_userdata
from cloudify.mocks import MockCloudifyContext
from cloudify.state import current_ctx
from cloudify_agent.api import defaults
from cloudify_agent.installer import script
from cosmo_tester.framework import util
from cosmo_tester.framework.fixtures import image_based_manager
from cosmo_tester.framework.util import (
    set_client_tenant,
    prepare_and_get_test_tenant,
)

manager = image_based_manager


EXPECTED_FILE_CONTENT = 'CONTENT'


def test_ubuntu_trusty_provided_userdata_agent(cfy,
                                               manager,
                                               attributes,
                                               tmpdir,
                                               logger):
    name = 'cloudify_agent'
    os_name = 'ubuntu_14_04'
    tenant = prepare_and_get_test_tenant(
        'userdataprov_{}'.format(os_name),
        manager,
        cfy,
    )
    install_userdata = _install_script(
        name=name,
        windows=False,
        user=attributes.ubuntu_14_04_username,
        manager=manager,
        attributes=attributes,
        tmpdir=tmpdir,
        logger=logger,
        tenant=tenant,
    )
    _test_linux_userdata_agent(
        cfy,
        manager,
        attributes,
        os_name,
        install_method='provided',
        name=name,
        install_userdata=install_userdata,
        tenant=tenant,
    )


def _test_agent(agent_type, cfy, manager, attributes):
    agent_blueprints = {
        'a3_2': 'agent/3-2-agent-blueprint/3-2-agent-mispelled-blprint.yaml',
        'ssh': 'agent/ssh-agent-blueprint/ssh-agent-blueprint.yaml',
    }

    blueprint_path = util.get_resource_path(agent_blueprints[agent_type])

    tenant = prepare_and_get_test_tenant(
        'agent_{}'.format(agent_type),
        manager,
        cfy,
    )
    blueprint_id = deployment_id = agent_type

    with set_client_tenant(manager, tenant):
        manager.client.blueprints.upload(blueprint_path, blueprint_id)
        manager.client.deployments.create(
            deployment_id, blueprint_id, inputs={
                'ip_address': manager.ip_address,
                'user': attributes.default_linux_username,
                'private_key_path': manager.remote_private_key_path
            }, skip_plugins_validation=True)
    try:
        cfy.executions.start.install(['-d', deployment_id,
                                      '--tenant-name', tenant])
    finally:
        cfy.executions.start.uninstall(['-d', deployment_id,
                                        '--tenant-name', tenant])


def _test_linux_userdata_agent(cfy, manager, attributes, os_name, tenant,
                               install_userdata=None, name=None,
                               install_method='init_script'):
    file_path = '/tmp/test_file'
    userdata = '#! /bin/bash\necho {0} > {1}\nchmod 777 {1}'.format(
        EXPECTED_FILE_CONTENT, file_path)
    if install_userdata:
        userdata = create_multi_mimetype_userdata([userdata,
                                                   install_userdata])

    inputs = {
        'image': attributes['{os}_image_name'.format(os=os_name)],
        'user': attributes['{os}_username'.format(os=os_name)],
        'flavor': attributes['small_flavor_name'],
        'os_family': 'linux',
        'userdata': userdata,
        'file_path': file_path,
        'install_method': install_method,
        'name': name,
        'keypair_name': attributes.keypair_name,
        'private_key_path': manager.remote_private_key_path,
        'network_name': attributes.network_name
    }

    _test_userdata_agent(cfy, manager, inputs, tenant)


def _test_userdata_agent(cfy, manager, inputs, tenant):
    blueprint_id = deployment_id = 'userdata{0}'.format(time.time())
    blueprint_path = util.get_resource_path(
        'agent/userdata-agent-blueprint/userdata-agent-blueprint.yaml')

    with set_client_tenant(manager, tenant):
        manager.client.blueprints.upload(blueprint_path, blueprint_id)
        manager.client.deployments.create(
            deployment_id,
            blueprint_id,
            inputs=inputs,
            skip_plugins_validation=True)

    cfy.executions.start.install(['-d', deployment_id,
                                  '--tenant-name', tenant])

    try:
        with set_client_tenant(manager, tenant):
            assert {
                'MY_ENV_VAR': 'MY_ENV_VAR_VALUE',
                'file_content': EXPECTED_FILE_CONTENT
            } == manager.client.deployments.outputs.get(deployment_id).outputs
    finally:
        cfy.executions.start.uninstall(['-d', deployment_id,
                                        '--tenant-name', tenant])


def _install_script(name, windows, user, manager, attributes, tmpdir, logger,
                    tenant):
    # Download cert from manager in order to include its content
    # in the init_script.
    local_cert_path = str(tmpdir / 'cloudify_internal_cert.pem')
    logger.info('Downloading internal cert from manager: %s -> %s',
                attributes.LOCAL_REST_CERT_FILE,
                local_cert_path)
    manager.get_remote_file(attributes.LOCAL_REST_CERT_FILE, local_cert_path)

    env_vars = {
        constants.REST_HOST_KEY: manager.private_ip_address,
        constants.REST_PORT_KEY: str(defaults.INTERNAL_REST_PORT),
        constants.BROKER_SSL_CERT_PATH: local_cert_path,
        constants.LOCAL_REST_CERT_FILE_KEY: local_cert_path,
        constants.MANAGER_FILE_SERVER_URL_KEY: (
            'https://{0}:{1}/resources'.format(manager.private_ip_address,
                                               defaults.INTERNAL_REST_PORT)
        ),
        constants.MANAGER_FILE_SERVER_ROOT_KEY: str(tmpdir),
        constants.MANAGER_NAME: (
            manager.client.manager.get_managers()[0].hostname
        ),
    }
    (tmpdir / 'cloudify_agent').mkdir()

    ctx = MockCloudifyContext(
        node_id='node',
        tenant=manager.client.tenants.get(tenant),
        rest_token=manager.client.tokens.get().value,
        managers=manager.client.manager.get_managers(),
        brokers=manager.client.manager.get_brokers(),
        properties={'agent_config': {
            'user': user,
            'windows': windows,
            'install_method': 'init_script',
            'name': name
        }})
    try:
        current_ctx.set(ctx)
        os.environ.update(env_vars)
        script_builder = script._get_script_builder()
        install_script = script_builder.install_script()
    finally:
        for var_name in list(env_vars):
            os.environ.pop(var_name, None)

        current_ctx.clear()

    # Replace the `main` call with an install call - as we only want to
    # install the agent, but not configure/start it
    install_method = 'InstallAgent' if windows else 'install_agent'
    install_script = '\n'.join(install_script.split('\n')[:-1])
    return '{0}\n{1}'.format(install_script, install_method)