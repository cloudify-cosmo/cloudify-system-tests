import pytest

from cosmo_tester.framework import util
from cosmo_tester.framework.examples import get_example_deployment


@pytest.fixture(scope='function')
def fake_vm(image_based_manager, ssh_key, logger, test_config):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, 'capability',
        test_config, upload_plugin=False)

    example.blueprint_file = util.get_resource_path(
        'blueprints/service_composition/fake_vm.yaml'
    )
    example.blueprint_id = 'fake_vm'
    example.deployment_id = 'fake_vm'
    example.inputs = {'agent_user': image_based_manager.username}
    yield example


@pytest.fixture(scope='function')
def proxied_plugin_file(image_based_manager, ssh_key, logger, test_config):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, 'capability', test_config)

    example.blueprint_file = util.get_resource_path(
        'blueprints/service_composition/capable_file.yaml'
    )
    example.blueprint_id = 'proxied_file'
    example.deployment_id = 'proxied_file'
    example.inputs['tenant'] = example.tenant
    del example.inputs['agent_user']
    # We don't need the secret as we won't be sshing to install the agent
    example.create_secret = False
    yield example


def test_capabilities(fake_vm,
                      proxied_plugin_file,
                      logger):
    # We're uploading a blueprint that creates an infrastructure for a VM,
    # and then exposes capabilities, which will be used in the application
    logger.info('Deploying infrastructure blueprint.')
    fake_vm.upload_blueprint()
    fake_vm.create_deployment()
    fake_vm.install()

    logger.info('Deploying application blueprint.')
    # This application relies on capabilities that it gets from the fake_vm,
    # as well as utilizing the new agent proxy ability to connect to an
    # agent of a node installed previously in another deployment (fake_vm)
    proxied_plugin_file.upload_and_verify_install()
    logger.info('File successfully validated.')

    proxied_plugin_file.uninstall()
