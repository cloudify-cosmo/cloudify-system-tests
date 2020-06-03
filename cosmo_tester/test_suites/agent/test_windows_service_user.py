from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.agent import get_test_prerequisites


def test_windows_with_service_user(ssh_key, module_tmpdir, test_config,
                                   logger, request):
    hosts, username, password = get_test_prerequisites(
        ssh_key, module_tmpdir, test_config, logger, request,
        'windows_2012',
    )
    manager, vm = hosts.instances

    service_user = '.\\testuser'
    service_password = 'svcpasS45'

    passed = True

    try:
        hosts.create()

        vm.wait_for_winrm()
        vm.run_windows_command("net user {user} {password} /add".format(
            user=service_user.split('\\', 1)[1],
            password=service_password,
        ))
        vm.run_windows_command(
            'net localgroup "Administrators" "{user}" /add'.format(
                user=service_user.split('\\', 1)[1],
            )
        )

        example = get_example_deployment(
            manager, ssh_key, logger, 'windows_service_user', test_config,
            vm=vm,
        )
        example.use_windows(username, password)
        example.inputs['service_user'] = service_user
        example.inputs['service_password'] = service_password
        example.upload_and_verify_install()
        example.uninstall()
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)
