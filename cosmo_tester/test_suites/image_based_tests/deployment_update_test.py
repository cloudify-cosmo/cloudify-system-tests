import pytest

from cosmo_tester.framework.deployment_update import (
    apply_and_check_deployment_update,
)
from cosmo_tester.framework.examples import get_example_deployment


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

    apply_and_check_deployment_update(image_based_manager, example_deployment,
                                      logger)

    logger.info('Uninstalling deployment')
    example_deployment.uninstall()
    logger.info('Checking new files were removed')
    example_deployment.check_all_test_files_deleted()
