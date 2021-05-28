from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import get_resource_path

from . import validate_agent


def test_agent_install_init_script(image_based_manager, ssh_key, logger,
                                   test_config):
    tenant = 'agent_install_init_script'
    example = get_example_deployment(image_based_manager, ssh_key, logger,
                                     tenant, test_config, init_script=True)
    example.blueprint_file = get_resource_path(
        'blueprints/compute/init_script.yaml'
    )
    example.upload_and_verify_install()
    validate_agent(image_based_manager, example, test_config,
                   install_method='init_script',
                   # Delete the next line (and broken_system in the validate
                   # function once the agent is fixed to get the right system.
                   broken_system=True)
    example.uninstall()
