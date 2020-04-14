from cosmo_tester.framework.examples.on_manager import OnManagerExample
from cosmo_tester.framework.util import prepare_and_get_test_tenant


# We can't make this a fixture as the bootstrap tests bootstrap the manager as
# part of the test, rather than part of the setup/teardown
def get_on_manager_example(cfy, manager, attributes, ssh_key, tmpdir, logger):
    tenant = prepare_and_get_test_tenant('bootstrap', manager,
                                         cfy, upload=False)

    manager.upload_test_plugin(tenant)

    example = OnManagerExample(
        cfy, manager, attributes, ssh_key, logger, tmpdir, tenant=tenant,
    )

    return example
