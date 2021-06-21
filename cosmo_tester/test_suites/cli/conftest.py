import pytest

from cosmo_tester.framework.test_hosts import Hosts, VM
from cosmo_tester.test_suites.cluster.conftest import _get_hosts

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

    cli_tests_dict = {'managers': [manager],
                      'tmpdir': session_tmpdir}

    try:
        hosts.create()
        manager.wait_for_ssh()

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


@pytest.fixture(scope='session')
def cluster_cli_tester(request, ssh_key, session_tmpdir, test_config,
                       session_logger):
    # Not including windows as we currently don't have any cluster tests that
    # target windows (see aio logs test for reason)
    all_targets = LINUX_OSES

    hosts = Hosts(
        ssh_key, session_tmpdir,
        test_config, session_logger, request, len(all_targets) + 3,
        bootstrappable=True,
    )

    cli_vms = {}
    for idx, cli_os in enumerate(all_targets):
        hosts.instances[idx + 3] = VM(cli_os, test_config)
        cli_vms[cli_os] = hosts.instances[idx + 3]

    passed = True

    try:
        hosts.create()

        managers = _get_hosts(
            hosts.instances[:3], test_config, session_logger,
            pre_cluster_rabbit=True, three_nodes_cluster=True)
        mgr1, mgr2, mgr3 = managers

        cli_tests_dict = {'managers': managers,
                          'tmpdir': session_tmpdir}

        for cli_os in all_targets:
            cli_host = cli_vms[cli_os]
            windows = 'windows' in cli_os

            if windows:
                prep_func = _prepare_windows_cli_test_components
            else:
                prep_func = _prepare_linux_cli_test_components

            cli_tests_dict[cli_os] = prep_func(
                cli_host, mgr1, cli_os, ssh_key, session_logger,
                test_config)

        yield cli_tests_dict
    except Exception:
        passed = False
        raise
    # Do not put this in a finally, let pytest handle that
    # Otherwise, --pdb will run /after/ the teardown
    hosts.destroy(passed=passed)
