import pytest


@pytest.fixture(scope='function')
def bootstrap_test_manager(session_manager):
    """Prepares a bootstrappable manager."""
    session_manager.wait_for_ssh()
    # We don't bootstrap here because bootstrapping in the test means that
    # --pdb will actually be useful as it'll allow investigation before
    # teardown on bootstrap failure
    yield session_manager
    if session_manager.bootstrapped:
        session_manager.teardown()
