import pytest

from cosmo_tester.framework.test_hosts import TestHosts


@pytest.fixture(scope='function')
def bootstrap_test_manager(request, cfy, ssh_key, module_tmpdir, test_config,
                           logger):
    """Prepares a bootstrappable manager."""
    hosts = TestHosts(
        cfy, ssh_key, module_tmpdir, test_config, logger,
        bootstrappable=True,
    )
    try:
        hosts.create()
        hosts.instances[0].wait_for_ssh()
        # We don't bootstrap here because bootstrapping in the test means that
        # --pdb will actually be useful as it'll allow investigation before
        # teardown on bootstrap failure
        yield hosts.instances[0]
    finally:
        hosts.destroy()
