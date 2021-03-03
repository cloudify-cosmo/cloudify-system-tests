import time

from cosmo_tester.framework.util import create_rest_client

ROOT_DN = 'cn=root,dc=cloudify,dc=test'
ROOT_PASSWORD = 'rootpass'


def test_slapd_ldaps_with_cluster(three_node_cluster_with_extra_node, logger):
    mgr1, mgr2, mgr3, slapd_host = three_node_cluster_with_extra_node

    users = {
        'user': {'uid': '15432', 'password': 'userpass',
                 'expected_groups': ['Cloudifiers']},
        'nester': {'uid': '15433', 'password': 'nesterpass',
                   'expected_groups': ['Cloudifiers', 'CloudyQA']},
    }
    groups = {
        'CloudyQA': {'members': ['uid=nester,ou=people,dc=cloudify,dc=test']},
        'Cloudifiers': {'members': [
            'uid=user,ou=people,dc=cloudify,dc=test',
            'cn=CloudyQA,ou=Departments,dc=cloudify,dc=test',
        ]},
    }

    _install_openldap(slapd_host, logger)
    ldap_ca_cert = _generate_and_retrieve_openldap_certs(slapd_host, logger)
    _configure_openldap(slapd_host, logger)
    _add_ous(slapd_host, logger)
    _add_users(slapd_host, users, logger)
    _add_groups(slapd_host, groups, logger)
    _disable_slapd_non_tls(slapd_host, logger)

    logger.info('Uploading cert to manager 1')
    mgr1.put_remote_file_content('/tmp/ldapca.pem', ldap_ca_cert)

    logger.info('Configuring ldap')
    # Using a call to the CLI in the expectation that we migrate ldap conf to
    # cfy_manager at some point- it's the sort of config that should be in the
    # admin CLI
    # This is deliberately using ldaps, as the other test (test_openldap)
    # covers ldap
    mgr1.run_command(
        "cfy ldap set "
        "-s ldaps://{}:636 "
        "--ldap-ca-path /tmp/ldapca.pem "
        "-d cloudify.test "
        "--ldap-group-dn 'ou=departments,{{base_dn}}' "
        "--ldap-group-member-filter '(member={{object_dn}})' "
        "--ldap-bind-format 'uid={{username}},ou=people,{{base_dn}}' "
        "--ldap-nested-levels 3".format(slapd_host.private_ip_address)
    )

    logger.info('Waiting for post-ldap-config restart')
    time.sleep(1)
    mgr1.wait_for_manager()
    mgr2.wait_for_manager()
    mgr3.wait_for_manager()

    logger.info('Configuring user group mappings')
    mgr1.client.user_groups.create(
        group_name='Cloudifiers',
        role='sys_admin',
        ldap_group_dn='cn=Cloudifiers,ou=Departments,dc=cloudify,dc=test',
    )
    mgr1.client.user_groups.create(
        group_name='CloudyQA',
        role='sys_admin',
        ldap_group_dn='cn=CloudyQA,ou=Departments,dc=cloudify,dc=test',
    )

    logger.info('Confirming admin user works on each manager')
    mgr1.client.manager.get_status()
    mgr2.client.manager.get_status()
    mgr3.client.manager.get_status()

    logger.info('Checking user log in and group membership')
    for user, details in users.items():
        for mgr in [mgr1, mgr2, mgr3]:
            mgr_ip = mgr.ip_address
            logger.info('Checking {user} on {mgr}'.format(
                user=user, mgr=mgr_ip,
            ))
            client = create_rest_client(
                mgr_ip,
                username=user,
                password=details['password'],
                protocol='https',
                cert=mgr.local_ca,
            )
            client.manager.get_status()
            logger.info('Checking group membership')
            mgr_details = mgr.client.users.list(username=user)[0]
            groups = mgr_details['group_system_roles'].get('sys_admin', [])
            assert sorted(groups) == sorted(details['expected_groups'])


def _install_openldap(host, logger):
    logger.info('Installing packages for openldap')
    host.run_command(
        'yum install -y openldap compat-openldap openldap-clients '
        'openldap-servers gnutls gnutls-utils',
        use_sudo=True,
    )
    logger.info('Starting openldap service')
    host.run_command('service slapd start', use_sudo=True)


def _generate_and_retrieve_openldap_certs(host, logger):
    logger.info('Preparing LDAP CA private key')
    host.run_command('mkdir /etc/ssl/private', use_sudo=True)
    host.run_command(
        'certtool --generate-privkey '
        '| sudo tee /etc/ssl/private/ldapcakey.pem >/dev/null'
    )
    logger.info('Generating LDAP CA public key')
    host.put_remote_file_content(
        '/tmp/ca.info',
        '''cn = testldapca
ca
cert_signing_key''',
    )
    host.run_command(
        'certtool --generate-self-signed '
        '--load-privkey /etc/ssl/private/ldapcakey.pem '
        '--template /tmp/ca.info '
        '--outfile /etc/ssl/certs/ldapcacert.crt',
        use_sudo=True,
    )
    logger.info('Retrieving LDAP CA cert contents')
    ca_cert = host.get_remote_file_content('/etc/ssl/certs/ldapcacert.crt')

    logger.info('Generating LDAP cert private key')
    host.run_command(
        'certtool --generate-privkey '
        '| sudo tee /etc/openldap/certs/ldap-key.pem >/dev/null'
    )
    logger.info('Generating LDAP cert')
    host.put_remote_file_content(
        '/tmp/cert.info',
        '''organization = Cloudifytest
cn = "{host_ip}"
tls_www_server
encryption_key
ip_address = "127.0.0.1"
ip_address = "{host_ip}"
signing_key'''.format(
            host_ip=host.private_ip_address,
        ),
    )
    host.run_command(
        'certtool --generate-certificate '
        '--load-privkey /etc/openldap/certs/ldap-key.pem '
        '--load-ca-certificate /etc/ssl/certs/ldapcacert.crt '
        '--load-ca-privkey /etc/ssl/private/ldapcakey.pem '
        '--template /tmp/cert.info '
        '--outfile /etc/openldap/certs/ldap-cert.pem',
        use_sudo=True,
    )

    return ca_cert


def _configure_openldap(host, logger):
    logger.info('Adding slapd root user')
    hashed_password = _get_slapd_password_hash(host, ROOT_PASSWORD)
    host.put_remote_file_content(
        '/tmp/setroot.ldif',
        '''dn: olcDatabase={2}hdb,cn=config
changetype: modify
replace: olcSuffix
olcSuffix: dc=cloudify,dc=test

dn: olcDatabase={2}hdb,cn=config
changetype: modify
replace: olcRootDN
olcRootDN: ''' + ROOT_DN + '''

dn: olcDatabase={2}hdb,cn=config
changetype: modify
replace: olcRootPW
olcRootPW: ''' + hashed_password + '\n'
    )
    host.run_command(
        'ldapmodify -Y EXTERNAL  -H ldapi:/// -f /tmp/setroot.ldif',
        use_sudo=True,
    )

    logger.info('Configure LDAP monitoring access')
    host.put_remote_file_content(
        '/tmp/mon.ldif',
        '''dn: olcDatabase={1}monitor,cn=config
changetype: modify
replace: olcAccess
olcAccess: {0}to * by dn.base="gidNumber=0+uidNumber=0,cn=peercred,cn=external, cn=auth" read by dn.base="'''  # noqa
        + ROOT_DN + '" read by * none'
    )
    host.run_command(
        'ldapmodify -Y EXTERNAL -H ldapi:/// -f /tmp/mon.ldif',
        use_sudo=True,
    )

    logger.info('Setting basic LDAP config')
    host.run_command(
        'cp /usr/share/openldap-servers/DB_CONFIG.example '
        '/var/lib/ldap/DB_CONFIG',
        use_sudo=True,
    )
    host.run_command(
        'chown -R ldap:ldap /var/lib/ldap/',
        use_sudo=True,
    )

    logger.info('Adding required LDAP schemas')
    host.run_command(
        'ldapadd -Y EXTERNAL -H ldapi:/// '
        '-f /etc/openldap/schema/cosine.ldif',
        use_sudo=True,
    )
    host.run_command(
        'ldapadd -Y EXTERNAL -H ldapi:/// -f /etc/openldap/schema/nis.ldif',
        use_sudo=True,
    )

    logger.info('Configuring ldaps')
    host.put_remote_file_content(
        '/tmp/certs.ldif',
        '''dn: cn=config
changetype: modify
replace: olcTLSCertificateKeyFile
olcTLSCertificateKeyFile: /etc/openldap/certs/ldap-key.pem
-
replace: olcTLSCertificateFile
olcTLSCertificateFile: /etc/openldap/certs/ldap-cert.pem
-
replace: olcTLSCACertificateFile
olcTLSCACertificateFile: /etc/ssl/certs/ldapcacert.crt''',
    )
    host.run_command(
        'ldapmodify -Y EXTERNAL -H ldapi:/// -f /tmp/certs.ldif',
        use_sudo=True,
    )
    # non-tls ldap needs to be left on for the initial config
    host.run_command(
        'sed -i "s#SLAPD_URLS=.*#SLAPD_URLS=\\"ldap:/// ldaps://{host_ip}/ '
        'ldapi:///\\"#" /etc/sysconfig/slapd'.format(
            host_ip=host.private_ip_address,
        ),
        use_sudo=True,
    )
    host.run_command('service slapd restart', use_sudo=True)


def _disable_slapd_non_tls(host, logger):
    logger.info('Disabling non-TLS ldap')
    host.run_command(
        'sed -i "s#SLAPD_URLS=.*#SLAPD_URLS=\\"ldaps://{host_ip}/ '
        'ldapi:///\\"#" /etc/sysconfig/slapd'.format(
            host_ip=host.private_ip_address,
        ),
        use_sudo=True,
    )
    host.run_command('service slapd restart', use_sudo=True)


def _add_ous(host, logger):
    logger.info('Creating base slapd OUs')
    host.put_remote_file_content(
        '/tmp/base.ldif',
        '''dn: dc=cloudify,dc=test
dc: cloudify
objectClass: top
objectClass: domain

dn: {root_dn}
objectClass: organizationalRole
cn: root
description: The boss

dn: ou=People,dc=cloudify,dc=test
objectClass: organizationalUnit
ou: People

dn: ou=Departments,dc=cloudify,dc=test
objectClass: organizationalUnit
ou: Departments'''.format(root_dn=ROOT_DN),
    )
    host.run_command(
        'ldapadd -x -w {root_pass} -D "{root_dn}" -f /tmp/base.ldif'.format(
            root_pass=ROOT_PASSWORD,
            root_dn=ROOT_DN,
        ),
        use_sudo=True,
    )


def _add_users(host, users, logger):
    for user, details in users.items():
        logger.info('Creating user {}'.format(user))
        host.put_remote_file_content(
            '/tmp/user_{}.ldif'.format(user),
            '''dn: uid={username},ou=people,dc=cloudify,dc=test
objectClass: top
objectClass: account
objectClass: posixAccount
objectClass: shadowAccount
cn: {username}
uid: {username}
uidNumber: {uid}
gidNumber: 100
homeDirectory: /home/{username}
loginShell: /bin/bash
gecos: {username}
userPassword: {password}
shadowLastChange: 0
shadowMax: 0
shadowWarning: 0'''.format(
                username=user,
                uid=details['uid'],
                password=_get_slapd_password_hash(host, details['password']),
            ),
        )
        host.run_command(
            'ldapadd -x -w {root_pass} -D "{root_dn}" '
            '-f /tmp/user_{user}.ldif'.format(
                root_pass=ROOT_PASSWORD,
                root_dn=ROOT_DN,
                user=user,
            ),
            use_sudo=True,
        )


def _add_groups(host, groups, logger):
    logger.info('Adding groups')
    for group, details in groups.items():
        logger.info('Adding group {}'.format(group))
        members = details['members']
        content = '''dn: cn={group},ou=Departments,dc=cloudify,dc=test
objectClass: top
objectClass: groupOfNames
'''
        for member in members:
            content += 'member: {}\n'.format(member)
        host.put_remote_file_content(
            '/tmp/group_{}.ldif'.format(group),
            content.format(group=group),
        )
        host.run_command(
            'ldapadd -x -w {root_pass} -D "{root_dn}" '
            '-f /tmp/group_{group}.ldif'.format(
                root_pass=ROOT_PASSWORD,
                root_dn=ROOT_DN,
                group=group,
            ),
            use_sudo=True,
        )


def _get_slapd_password_hash(host, password):
    # This puts the password in ldap using SHA1, which is terrible but
    # will suffice for testing
    return host.run_command(
        '/usr/sbin/slappasswd -s {}'.format(password)).stdout
