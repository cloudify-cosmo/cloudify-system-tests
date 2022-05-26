from cosmo_tester.test_suites.cli import (
    _cleanup_profile,
    LINUX_OSES,
    _prepare,
    _test_cfy_install,
    _test_teardown,
    _test_upload_and_install,
    WINDOWS_OSES,
)


def test_cli_deployment_flow(cli_tester, logger):
    for os in LINUX_OSES + WINDOWS_OSES:
        cli_host = cli_tester[os]['cli_host']
        example = cli_tester[os]['example']
        paths = cli_tester[os]['paths']

        _prepare(cli_host, example, paths, logger)

        _test_upload_and_install(cli_host.run_command, example, paths, logger)

        _test_teardown(cli_host.run_command, example, paths, logger)

        _cleanup_profile(cli_host.run_command, example, paths, logger)


def test_cli_install_flow(cli_tester, logger):
    for os in LINUX_OSES + WINDOWS_OSES:
        cli_host = cli_tester[os]['cli_host']
        example = cli_tester[os]['example']
        paths = cli_tester[os]['paths']

        _prepare(cli_host, example, paths, logger)

        _test_cfy_install(cli_host.run_command, example, paths, logger)

        _test_teardown(cli_host.run_command, example, paths, logger)

        _cleanup_profile(cli_host.run_command, example, paths, logger)
