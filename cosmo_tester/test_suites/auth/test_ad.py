import time

from retrying import retry
import pytest

from cosmo_tester.framework.test_hosts import Hosts, VM

BASE_DN = 'dc=cloudifyad,dc=test'


def test_ad_with_aio(windows_ldap_tester, logger):
    mgr, ad_host = windows_ldap_tester

    users = {
        'DefUser': {'password': 'Du123456!',
                    'parent': 'cn=users,' + BASE_DN,
                    'expected_groups': ['Defers']},
        'DefNestUser': {'password': 'Dnu123456!',
                        'parent': 'cn=users,' + BASE_DN,
                        'expected_groups': ['Defers']},
        'OddDefUser': {'password': 'Odu123456!',
                       'parent': 'cn=users,' + BASE_DN,
                       'expected_groups': []},
        'DefBothUser': {'password': 'Dbu123456!',
                        'parent': 'cn=users,' + BASE_DN,
                        'expected_groups': ['Defers', 'Alters']},
        'AltUser': {'password': 'Au123456!',
                    'parent': 'ou=accounts,ou=nonstandard,' + BASE_DN,
                    'expected_groups': ['Alters']},
        'AltNestUser': {'password': 'Anu123456!',
                        'parent': 'ou=accounts,ou=nonstandard,' + BASE_DN,
                        'expected_groups': ['Alters']},
        'OddAltUser': {'password': 'Oau123456!',
                       'parent': 'ou=accounts,ou=nonstandard,' + BASE_DN,
                       'expected_groups': []},
        'AltBothUser': {'password': 'Abu123456!',
                        'parent': 'ou=accounts,ou=nonstandard,' + BASE_DN,
                        'expected_groups': ['Alters', 'Defers']},
    }
    groups = {
        'DefGroup': {
            'parent': 'ou=groups,' + BASE_DN,
            'members': ['DefNestGroup1', 'DefUser',
                        'DefBothUser', 'AltBothUser'],
        },
        'DefNestGroup1': {
            'parent': 'ou=groups,' + BASE_DN,
            'members': ['DefNestGroup2'],
        },
        'DefNestGroup2': {
            'parent': 'ou=groups,' + BASE_DN,
            'members': ['DefNestUser'],
        },
        'AltGroup': {
            'parent': 'ou=departments,ou=nonstandard,' + BASE_DN,
            'members': ['AltNestGroup1', 'AltUser',
                        'DefBothUser', 'AltBothUser'],
        },
        'AltNestGroup1': {
            'parent': 'ou=departments,ou=nonstandard,' + BASE_DN,
            'members': ['AltNestGroup2'],
        },
        'AltNestGroup2': {
            'parent': 'ou=departments,ou=nonstandard,' + BASE_DN,
            'members': ['AltNestUser'],
        },
    }

    _add_ous(ad_host, logger)
    _add_users(ad_host, users, logger)
    _add_groups(ad_host, groups, logger)

    logger.info('Configuring ldap')
    # Using a call to the CLI in the expectation that we migrate ldap conf to
    # cfy_manager at some point- it's the sort of config that should be in the
    # admin CLI
    # This is deliberately not using ldaps, as the other test (test_openldap)
    # covers ldaps
    mgr.run_command(
        "cfy ldap set "
        "-s ldap://{}:389 "
        "-d cloudifyad.test "
        "-a "
        "--ldap-nested-levels 3".format(ad_host.private_ip_address),
    )

    logger.info('Waiting for post-ldap-config restart')
    time.sleep(1)
    mgr.wait_for_manager()

    logger.info('Configuring user group mappings')
    mgr.client.user_groups.create(
        group_name='Defers',
        role='sys_admin',
        ldap_group_dn='cn=defgroup,ou=groups,dc=cloudifyad,dc=test',
    )
    mgr.client.user_groups.create(
        group_name='Alters',
        role='sys_admin',
        ldap_group_dn=(
            'cn=altgroup,ou=departments,ou=nonstandard,dc=cloudifyad,dc=test'
        ),
    )

    logger.info('Checking user log in and group membership')
    for user, details in users.items():
        logger.info('Checking {user} on {mgr}'.format(
            user=user, mgr=mgr.ip_address,
        ))
        client = mgr.get_rest_client(
            username=user,
            password=details['password'],
        )
        client.manager.get_status()
        logger.info('Checking group membership')
        mgr_details = mgr.client.users.list(username=user)[0]
        groups = mgr_details['group_system_roles'].get('sys_admin', [])
        assert sorted(groups) == sorted(details['expected_groups'])


def _add_ous(ad_host, logger):
    logger.info('Creating base AD OUs')
    ous = [
        ('Groups', BASE_DN),
        ('NonStandard', BASE_DN),
        ('Accounts', 'ou=nonstandard,' + BASE_DN),
        ('Departments', 'ou=nonstandard,' + BASE_DN),
    ]
    for name, path in ous:
        logger.info('Creating OU %s under %s', name, path)
        ad_host.run_command(
            'New-ADOrganizationalUnit -Name {name} -Path "{path}"'.format(
                name=name, path=path,
            ),
            powershell=True,
        )


def _add_users(ad_host, users, logger):
    logger.info('Creating AD users')
    for user, details in users.items():
        logger.info('Adding user %s', user)
        ad_host.run_command(
            'New-ADUser -Name {name} -Path "{path}"'.format(
                name=user, path=details['parent'],
            ),
            powershell=True,
        )
        logger.info('Setting password for %s', user)
        ad_host.run_command(
            'Set-ADAccountPassword -Identity \'cn={name},{parent}\' -Reset '
            '-NewPassword (ConvertTo-SecureString -AsPlainText '
            '"{password}" -Force)'.format(
                name=user,
                parent=details['parent'],
                password=details['password'],
            ),
            powershell=True,
        )
        ad_host.run_command(
            'Set-ADUser -ChangePasswordAtLogon 0 -Identity {name}'.format(
                name=user,
            ),
            powershell=True,
        )
        logger.info('Enabling account for %s', user)
        ad_host.run_command(
            'Enable-ADAccount -Identity {name}'.format(name=user),
            powershell=True,
        )


def _add_groups(ad_host, groups, logger):
    logger.info('Creating AD groups')
    for group, details in groups.items():
        logger.info('Creating %s under %s', group, details['parent'])
        ad_host.run_command(
            'New-ADGroup -Name {name} -Path "{path}" '
            '-GroupScope Global'.format(
                name=group,
                path=details['parent'],
            ),
            powershell=True,
        )
    logger.info('Assigning group members')
    for group, details in groups.items():
        members = ','.join(details['members'])
        logger.info('Assigning %s group members: %s', group, members)
        ad_host.run_command(
            'Add-ADGroupMember -Identity "{group}" -Members {members} '
            '-Confirm:$False'.format(
                group=group,
                members=members,
            ),
            powershell=True,
        )


@pytest.fixture(scope='function')
def windows_ldap_tester(request, ssh_key, module_tmpdir, test_config, logger):
    windows_image = 'windows_2012'

    ldap_hosts = Hosts(
        ssh_key, module_tmpdir,
        test_config, logger, request, 2,
    )
    ldap_hosts.instances[1] = VM(windows_image, test_config)
    username = ldap_hosts.instances[1].username

    add_firewall_cmd = "&netsh advfirewall firewall add rule"
    ldap_hosts.instances[1].userdata = '''#ps1_sysnative
$PSDefaultParameterValues['*:Encoding'] = 'utf8'

Write-Host "## Installing AD domain services"
Install-windowsfeature AD-domain-services -IncludeManagementTools
Import-Module ADDSDeployment

Write-Host "## Setting password for Admin user..."
$name = hostname
([adsi]"WinNT://$name/{username}").SetPassword("{password}")

Write-Host "## Installing AD forest"
$secure_string_pwd = convertto-securestring "P@ssW0rD!" -asplaintext -force
Install-ADDSForest -DomainName cloudifyad.test -SafeModeAdministratorPassword $secure_string_pwd -Force

Write-Host "## Configuring WinRM and firewall rules.."
winrm quickconfig -q
winrm set winrm/config              '@{{MaxTimeoutms="1800000"}}'
winrm set winrm/config/winrs        '@{{MaxMemoryPerShellMB="300"}}'
winrm set winrm/config/service      '@{{AllowUnencrypted="true"}}'
winrm set winrm/config/service/auth '@{{Basic="true"}}'
{fw_cmd} name="WinRM 5985" protocol=TCP dir=in localport=5985 action=allow
{fw_cmd} name="WinRM 5986" protocol=TCP dir=in localport=5986 action=allow
Restart-Computer'''.format(username=username, fw_cmd=add_firewall_cmd,  # noqa
                           password=ldap_hosts.instances[1].password)

    passed = True

    try:
        ldap_hosts.create()
        ldap_hosts.instances[1].wait_for_winrm()
        _wait_for_ad(ldap_hosts.instances[1], logger)
        logger.info('Waiting to ensure windows host has rebooted')
        time.sleep(10)
        ldap_hosts.instances[1].wait_for_winrm()

        yield ldap_hosts.instances
    except Exception:
        passed = False
        raise
    finally:
        ldap_hosts.destroy(passed=passed)


@retry(stop_max_attempt_number=60, wait_fixed=3000)
def _wait_for_ad(host, logger):
    logger.info('Checking that AD is installed...')
    res = host.run_command('Get-ADForest', powershell=True)
    assert 'cloudifyad.test' in res.stdout.decode('utf-8')
    logger.info('...AD is installed.')
