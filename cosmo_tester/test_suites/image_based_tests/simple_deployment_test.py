from cosmo_tester.framework.examples import get_example_deployment


def test_simple_deployment(image_based_manager, ssh_key, tmpdir, logger,
                           test_config):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, 'simple_deployment',
        test_config)
    example.upload_and_verify_install()
    example.uninstall()
