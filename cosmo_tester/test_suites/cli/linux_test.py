from cosmo_tester.test_suites.cli import (
    _prepare,
    _test_cfy_install,
    _test_teardown,
    _test_upload_and_install,
)


def test_cli_deployment_flow_linux(linux_cli_tester, logger):
    cli_host = linux_cli_tester['cli_host']
    example = linux_cli_tester['example']
    paths = linux_cli_tester['paths']

    _prepare(cli_host.run_command, example, paths, logger)

    _test_upload_and_install(cli_host.run_command, example, paths, logger)

    _test_teardown(cli_host.run_command, example, paths, logger)


def test_cli_install_flow_linux(linux_cli_tester, logger):
    cli_host = linux_cli_tester['cli_host']
    example = linux_cli_tester['example']
    paths = linux_cli_tester['paths']

    _prepare(cli_host.run_command, example, paths, logger)

    _test_cfy_install(cli_host.run_command, example, paths, logger)

    _test_teardown(cli_host.run_command, example, paths, logger)
