from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import get_resource_path


def test_3_2_agent_install(cfy, image_based_manager, ssh_key, logger,
                           test_config):
    # Check agent install with the 3.2 types and 1.2 DSL version via ssh
    example = get_example_deployment(image_based_manager, ssh_key, logger,
                                     'agent_install_3_2', test_config,
                                     upload_plugin=False)
    example.blueprint_file = get_resource_path(
        'blueprints/compute/example_3_2.yaml'
    )
    example.upload_and_verify_install(skip_plugins_validation=True)
    example.uninstall()
