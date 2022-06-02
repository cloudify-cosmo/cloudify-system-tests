from cosmo_tester.framework.util import create_rest_client
from cosmo_tester.test_suites.auth.saml_responses import make_response

import requests

from base64 import b64encode

SIGNING_SCRIPT = '/tmp/generate_signed_saml'
TMP_FOR_SIGNING = '/tmp/saml_for_signing'
TMP_SIGNED = '/tmp/signed_saml'
INTERNAL_CERT = '/etc/cloudify/ssl/cloudify_internal_cert.pem'
INTERNAL_KEY = '/etc/cloudify/ssl/cloudify_internal_key.pem'
SAML_CERT = '/etc/cloudify/ssl/okta_certificate.pem'


def test_saml_auth(image_based_manager, logger):
    _activate_saml_auth(image_based_manager, logger)

    _deploy_signing_script(image_based_manager, logger)

    logger.info('Confirming OK endpoint works without authentication')
    assert requests.get(
        f'https://{image_based_manager.ip_address}/api/v3.1/ok',
        verify=image_based_manager.api_ca_path).text.strip() == '"OK"'

    image_based_manager.client.user_groups.create('Everyone',
                                                  role='sys_admin')

    before_users = set(user['username']
                       for user in image_based_manager.client.users.list())

    problems = []
    problems.extend(_test_login_with_all_attrs_set(image_based_manager))
    problems.extend(_test_login_with_no_extra_attrs(image_based_manager))
    problems.extend(_test_login_with_unknown_groups(image_based_manager))
    problems.extend(_test_login_with_bad_signature(image_based_manager))
    problems.extend(_test_login_before_valid(image_based_manager))
    problems.extend(_test_login_after_expiry(image_based_manager))

    after_users = set(user['username']
                      for user in image_based_manager.client.users.list())

    added_users = after_users - before_users
    problems.extend(_clean_users(image_based_manager, added_users, logger))

    clean_users = set(user['username']
                      for user in image_based_manager.client.users.list())

    if clean_users != before_users:
        problems.append(
            'Not all users were deleted correctly.\n'
            f'Before: {before_users}\n'
            f'After: {clean_users}'
        )

    assert not problems, (
        '\n'.join(problems)
    )


def _activate_saml_auth(manager, logger):
    logger.info('Putting SAML cert in location and restarting rest service')
    manager.run_command(f'sudo cp {INTERNAL_CERT} {SAML_CERT}')
    manager.run_command('sudo supervisorctl restart cloudify-restservice')
    logger.info('Waiting for manager service to finish restarting.')
    manager.wait_for_manager()

    logger.info('Checking IDP mode is okta')
    assert manager.client.idp.get() == 'okta'


def _deactivate_saml_auth(manager, logger):
    logger.info('Disabling SAML auth')
    manager.run_command(f'sudo rm {SAML_CERT}')
    manager.run_command('sudo supervisorctl restart cloudify-restservice')
    logger.info('Waiting for manager service to finish restarting.')
    manager.wait_for_manager()


def _deploy_signing_script(manager, logger):
    logger.info('Deploying signing script and setting permissions')
    manager.put_remote_file_content(
        SIGNING_SCRIPT,
        f'''#! /opt/manager/env/bin/python
from lxml import etree
from signxml import XMLSigner

with open('{TMP_FOR_SIGNING}') as data_handle:
    data = data_handle.read()
data = etree.fromstring(data.encode('utf8'))

with open('{INTERNAL_CERT}') as cert_handle:
    cert = cert_handle.read()

with open('{INTERNAL_KEY}') as key_handle:
    key = key_handle.read()

signer = XMLSigner(c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
signed_data = signer.sign(data=data, cert=cert, key=key)
signed_data.getroottree().write('{TMP_SIGNED}')
''')
    manager.run_command(f'chmod 755 {SIGNING_SCRIPT}')


def _clean_users(manager, users, logger):
    problems = []

    _deactivate_saml_auth(manager, logger)

    idp_mode = manager.client.idp.get()
    if idp_mode != 'local':
        problems.append(f'Manager IDP mode should be local, was:{idp_mode}')

    for user in users:
        try:
            if manager.client.users.get(user)['groups']:
                manager.client.user_groups.remove_user(user, 'Everyone')
            manager.client.users.delete(user)
        except Exception as err:
            problems.append(f'Failed to delete user {user}: {err}')

    return problems


def _get_signed_saml_doc(manager, saml_doc, bad_signature=False):
    manager.put_remote_file_content(TMP_FOR_SIGNING, saml_doc)
    manager.run_command(f'sudo {SIGNING_SCRIPT}')
    manager.run_command(f'sudo chown $(whoami). {TMP_SIGNED}')

    saml_doc = manager.get_remote_file_content(TMP_SIGNED)
    if bad_signature:
        junk_data = 'badsig'

        sig_marker = 'SignatureValue>'
        sig_position = saml_doc.index(sig_marker) + len(sig_marker)

        before_sig = saml_doc[:sig_position]
        from_sig = saml_doc[sig_position:]

        if from_sig.startswith(junk_data):
            junk_data = junk_data.upper()
        from_sig = junk_data + from_sig[len(junk_data):]

        saml_doc = before_sig + from_sig

    return saml_doc


def _request_token(manager, auth_request, expect_fail=False):
    result = requests.post(
        f'https://{manager.ip_address}/api/v3.1/tokens',
        json={
            'saml-response': b64encode(
                auth_request.encode('utf8')).decode('utf8')},
        verify=manager.api_ca_path,
    )

    if expect_fail:
        assert result.status_code == 401
        assert not result.json().get('server_traceback')
    else:
        return result.json()


def _test_login_with_all_attrs_set(manager):
    users = {
        style: {
            'username': f'testuserallattrs@{style}.local',
            'first_name': f'FirstAll{style}',
            'last_name': f'LastAll{style}',
            'email': f'testuserallattrs@{style}.local',
            'groups': ['Everyone', style],
        }
        for style in ['okta', 'azure']
    }

    return _test_login_with_attrs(manager, users)


def _test_login_with_no_extra_attrs(manager):
    users = {
        style: {
            'username': f'testusernoattrs@{style}.local',
        }
        for style in ['okta', 'azure']
    }

    return _test_login_with_attrs(manager, users)


def _test_login_with_unknown_groups(manager):
    users = {
        style: {
            'username': f'testusernoattrs@{style}.local',
            'groups': ['unknown', style],
        }
        for style in ['okta', 'azure']
    }

    return _test_login_with_attrs(manager, users)


def _test_login_with_attrs(manager, users):
    problems = []

    azure_auth = _get_signed_saml_doc(
        manager, make_response(**users['azure'], style='azure'),
    )
    okta_auth = _get_signed_saml_doc(
        manager, make_response(**users['okta'], style='okta'),
    )

    try:
        azure_token = _request_token(manager, azure_auth)
    except Exception as err:
        problems.append('Error using azure auth: {}'.format(err))
    try:
        okta_token = _request_token(manager, okta_auth)
    except Exception as err:
        problems.append('Error using okta auth: {}'.format(err))

    problems.extend(_check_users(manager, users))

    azure_token_issue = _check_token(manager, azure_token)
    if azure_token_issue:
        problems.append(f'Problem with azure token: {azure_token_issue}')
    okta_token_issue = _check_token(manager, okta_token)
    if okta_token_issue:
        problems.append(f'Problem with okta token: {okta_token_issue}')

    return problems


def _check_users(manager, users):
    problems = []

    for user in users.values():
        username = user['username']
        user_details = manager.client.users.get(username)

        expected_group_count = 0
        expected_group_system_roles = {}

        saml_groups = user.get('groups', {})
        if 'Everyone' in saml_groups:
            expected_group_count = 1
            expected_group_system_roles = {'sys_admin': ['Everyone']}

        actual_group_count = user_details['groups']
        actual_group_system_roles = user_details['group_system_roles']

        if actual_group_count != expected_group_count:
            problems.append(
                f'{username} does not have expected group count: '
                f'{actual_group_count} != {expected_group_count}')
        if actual_group_system_roles != expected_group_system_roles:
            problems.append(
                f'{username} does not have expected group system roles: '
                f'{actual_group_system_roles} '
                f'!= {expected_group_system_roles}')

    return problems


def _test_login_with_bad_signature(manager):
    users = {
        style: {
            'username': f'testusernoattrs@{style}.local',
        }
        for style in ['okta', 'azure']
    }

    return _check_bad_conditions(manager, users, check_type='bad_signature')


def _test_login_before_valid(manager):
    users = {
        style: {
            'username': f'testusernoattrs@{style}.local',
        }
        for style in ['okta', 'azure']
    }

    return _check_bad_conditions(manager, users, check_type='too_soon')


def _test_login_after_expiry(manager):
    users = {
        style: {
            'username': f'testusernoattrs@{style}.local',
        }
        for style in ['okta', 'azure']
    }

    return _check_bad_conditions(manager, users, check_type='expired')


def _check_bad_conditions(manager, users, check_type):
    problems = []

    expired = False
    too_soon = False
    bad_signature = False
    if check_type == 'expired':
        expired = True
    elif check_type == 'too_soon':
        too_soon = True
    elif check_type == 'bad_signature':
        bad_signature = True
    else:
        raise RuntimeError(f'{check_type} is not a valid check type.')

    azure_auth = _get_signed_saml_doc(
        manager,
        make_response(**users['azure'], style='azure',
                      expired=expired, too_soon=too_soon),
        bad_signature=bad_signature,
    )
    okta_auth = _get_signed_saml_doc(
        manager,
        make_response(**users['okta'], style='okta',
                      expired=expired, too_soon=too_soon),
        bad_signature=bad_signature,
    )

    try:
        _request_token(manager, azure_auth, expect_fail=True)
    except Exception as err:
        message = f'Incorrect response checking {check_type} azure auth: '
        problems.append(f'{message}{err}')
    try:
        _request_token(manager, okta_auth, expect_fail=True)
    except Exception as err:
        message = f'Incorrect response checking {check_type} okta auth: '
        problems.append(f'{message}{err}')

    return problems


def _check_token(manager, token):
    client = create_rest_client(manager.ip_address,
                                token=token['value'],
                                tenant='default_tenant',
                                cert=manager.api_ca_path,
                                protocol='https')
    try:
        client.manager.get_status()
    except Exception as err:
        return err
