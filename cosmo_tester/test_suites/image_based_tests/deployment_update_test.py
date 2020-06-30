import pytest

from retrying import retry

from cosmo_tester.framework import util
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import set_client_tenant


update_counter = 0


@pytest.fixture(scope='function')
def example_deployment(image_based_manager, ssh_key, logger,
                       test_config):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, 'dep_update', test_config)

    yield example


def test_simple_deployment_update(image_based_manager,
                                  example_deployment,
                                  logger):
    example_deployment.upload_and_verify_install()

    modified_blueprint_path = util.get_resource_path(
        'blueprints/compute/example_2_files.yaml'
    )
    blueprint_id = 'updated'
    with set_client_tenant(image_based_manager.client,
                           example_deployment.tenant):
        image_based_manager.client.blueprints.upload(
            modified_blueprint_path,
            blueprint_id,
        )

    logger.info('Updating example deployment...')
    _update_deployment(image_based_manager.client,
                       example_deployment.deployment_id,
                       example_deployment.tenant,
                       blueprint_id,
                       logger,
                       skip_reinstall=True)

    logger.info('Checking old files still exist')
    example_deployment.check_files()

    original_path = example_deployment.inputs['path']
    updated_path = '/tmp/new_test'
    updated_content = 'Where are the elephants?'

    logger.info('Checking new files exist')
    example_deployment.check_files(path='/tmp/test_announcement',
                                   expected_content='I like cake')

    logger.info('Preparing for updated deployment')
    # We have to clean up beforehand because the update uses the new inputs
    # instead of the old ones for the uninstall, which will fail if we don't
    # prepare.
    with set_client_tenant(image_based_manager.client,
                           example_deployment.tenant):
        inst_id = util.get_node_instances(
            'file', example_deployment.deployment_id,
            image_based_manager.client,
        )[0]['id']
    suffix = inst_id.split('_')[-1]
    image_based_manager.run_command('rm {}_*'.format(original_path))
    image_based_manager.put_remote_file_content(
        remote_path='{}_file_{}'.format(updated_path, suffix),
        content=updated_content,
    )

    logger.info('Updating deployment to use different path and content')
    _update_deployment(image_based_manager.client,
                       example_deployment.deployment_id,
                       example_deployment.tenant,
                       example_deployment.blueprint_id,
                       logger,
                       inputs={'path': updated_path,
                               'content': updated_content})

    logger.info('Checking new files were created')
    example_deployment.check_files(
        path=updated_path,
        expected_content=updated_content,
    )
    logger.info('Checking old files were removed')
    # This will look for the originally named files
    example_deployment.check_all_test_files_deleted()

    logger.info('Uninstalling deployment')
    example_deployment.uninstall()
    logger.info('Checking new files were removed')
    example_deployment.check_all_test_files_deleted(path=updated_path)


@retry(stop_max_attempt_number=10, wait_fixed=5000)
def wait_for_deployment_update(client, execution_id, logger):
    logger.info('Checking deployment update with execution ID: {}'.format(
        execution_id))
    dep_update = client.deployment_updates.list(
        execution_id=execution_id)[0]
    assert dep_update['state'] == 'successful'


def _update_deployment(client,
                       deployment_id,
                       tenant,
                       blueprint_id,
                       logger,
                       skip_reinstall=False,
                       inputs=None):
    with set_client_tenant(client, tenant):
        dep_update = client.deployment_updates.update_with_existing_blueprint(
            deployment_id=deployment_id,
            blueprint_id=blueprint_id,
            skip_reinstall=skip_reinstall,
            inputs=inputs,
        )
        logger.info('Waiting for deployment update to complete...')
        execution = client.executions.list(id=dep_update['execution_id'])[0]
        util.wait_for_execution(client, execution, logger)

        wait_for_deployment_update(client, dep_update['execution_id'], logger)
        logger.info('Deployment update complete.')
