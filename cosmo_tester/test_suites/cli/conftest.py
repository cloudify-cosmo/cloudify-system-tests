import pytest

from cosmo_tester.framework.test_hosts import Hosts, VM

from . import (
    LINUX_OSES,
    _prepare_linux_cli_test_components,
    _prepare_windows_cli_test_components,
    WINDOWS_OSES,
)


@pytest.fixture(scope='session')
def cli_tester(request, ssh_key, session_tmpdir, test_config,
               session_logger):
    all_targets = LINUX_OSES + WINDOWS_OSES

    hosts = Hosts(
        ssh_key, session_tmpdir,
        test_config, session_logger, request, len(all_targets) + 1,
    )

    manager = hosts.instances[0]

    cli_vms = {}
    for idx, cli_os in enumerate(all_targets):
        hosts.instances[idx + 1] = VM(cli_os, test_config)
        cli_vms[cli_os] = hosts.instances[idx + 1]

    passed = True

    cli_tests_dict = {'manager': manager,
                      'tmpdir': session_tmpdir}

    try:
        hosts.create()

        for cli_os in all_targets:
            cli_host = cli_vms[cli_os]
            windows = 'windows' in cli_os

            if windows:
                prep_func = _prepare_windows_cli_test_components
            else:
                prep_func = _prepare_linux_cli_test_components

            cli_tests_dict[cli_os] = prep_func(
                cli_host, manager, cli_os, ssh_key, session_logger,
                test_config)

        yield cli_tests_dict
    except Exception:
        passed = False
        raise
    # Do not put this in a finally, let pytest handle that
    # Otherwise, --pdb will run /after/ the teardown
    hosts.destroy(passed=passed)
