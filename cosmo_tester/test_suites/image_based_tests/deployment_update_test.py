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
    example.uninstall()


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
    _update_deployment(image_based_manager,
                       example_deployment.deployment_id,
                       example_deployment.tenant,
                       blueprint_id,
                       skip_reinstall=True)

    logger.info('Checking old files still exist')
    example_deployment.check_files()

    logger.info('Checking new files exist')
    example_deployment.check_files(path='/tmp/test_announcement',
                                   expected_content='I like cake')

    logger.info('Updating deployment to use different path and content')
    _update_deployment(image_based_manager,
                       example_deployment.deployment_id,
                       example_deployment.tenant,
                       example_deployment.blueprint_id,
                       inputs={'path': '/tmp/new_test',
                               'content': 'Where are the elephants?'})

    logger.info('Checking new files were created')
    example_deployment.check_files(
        path='/tmp/new_test',
        expected_content='Where are the elephants?',
    )
    logger.info('Checking old files were removed')
    # This will look for the originally named files
    example_deployment.check_all_test_files_deleted()

    logger.info('Uninstalling deployment')
    example_deployment.uninstall()
    logger.info('Checking new files were removed')
    example_deployment.check_all_test_files_deleted(path='/tmp/new_test')


def _wait_for_deployment_update_to_finish(func):
    def _update_and_wait_to_finish(manager,
                                   deployment_id,
                                   tenant,
                                   *args,
                                   **kwargs):
        func(manager, deployment_id, tenant, *args, **kwargs)

        @retry(stop_max_attempt_number=10,
               wait_fixed=5000,
               retry_on_result=lambda r: not r)
        def repetitive_check():
            with set_client_tenant(manager.client, tenant):
                dep_updates_list = manager.client.deployment_updates.list(
                        deployment_id=deployment_id)
                executions_list = manager.client.executions.list(
                        deployment_id=deployment_id,
                        workflow_id='update',
                        _include=['status']
                )
            if len(dep_updates_list) != update_counter:
                return False
            for deployment_update in dep_updates_list:
                if deployment_update.state not in ['failed', 'successful']:
                    return False
            for execution in executions_list:
                if execution['status'] not in ['terminated',
                                               'failed',
                                               'cancelled']:
                    return False
            return True
        repetitive_check()
    return _update_and_wait_to_finish


@_wait_for_deployment_update_to_finish
def _update_deployment(manager,
                       deployment_id,
                       tenant,
                       blueprint_id,
                       skip_reinstall=False,
                       inputs=None):
    global update_counter
    update_counter += 1
    with set_client_tenant(manager.client, tenant):
        manager.client.deployment_updates.update_with_existing_blueprint(
            deployment_id=deployment_id,
            blueprint_id=blueprint_id,
            skip_reinstall=skip_reinstall,
            inputs=inputs,
        )
