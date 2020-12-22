import json

REMOTE_CERT_PATH = '/etc/cloudify/ssl/cloudify_internal_ca_cert.pem'
REMOTE_CONF_PATH = '/opt/manager/rest-security.conf'
REMOTE_HOOKS_PATH = '/opt/mgmtworker/config/hooks.conf'
AUTH_MQ_USER_CMD = 'sudo rabbitmqctl -n rabbit@localhost ' \
                   'authenticate_user -- "{user}" "{password}"'

NEW_TENANT = 'new_tenant'
NEW_KEY = 'new_key'
NEW_VALUE = 'new_value'
NEW_HOOKS = 'new_hooks'

GET_MQ_PASSWORDS_CODE_PATH = '/tmp/get_passwords.py'
MQ_PASSWORDS_PATH = '/tmp/passwords'
GET_MQ_PASSWORDS_CODE = '''
import os
import json

from cloudify.cryptography_utils import decrypt

from manager_rest.storage import models
from manager_rest.flask_utils import setup_flask_app

os.environ['MANAGER_REST_CONFIG_PATH'] = '/opt/manager/cloudify-rest.conf'
setup_flask_app()

tenants = models.Tenant.query.all()
decrypted_passwords = {t.rabbitmq_username:
                           decrypt(t.rabbitmq_password) for t in tenants}
with open('%s', 'w') as f:
    json.dump(decrypted_passwords, f)
''' % MQ_PASSWORDS_PATH


def test_cfy_manager_configure(image_based_manager, logger, test_config):
    logger.info('Putting code to get decrypted passwords on manager...')
    image_based_manager.put_remote_file_content(
        remote_path=GET_MQ_PASSWORDS_CODE_PATH,
        content=GET_MQ_PASSWORDS_CODE
    )

    logger.info('Getting current CA cert from the manager...')
    old_cert = image_based_manager.get_remote_file_content(REMOTE_CERT_PATH)

    tenants_to_check = ['default_tenant']

    # Creating new tenants is a premium-only feature
    if test_config['premium']:
        logger.info('Creating new tenant and '
                    'validating RMQ user was created...')
        image_based_manager.client.tenants.create(NEW_TENANT)
        tenants_to_check.append(NEW_TENANT)

    mq_passwords = _get_mq_passwords(image_based_manager)

    for tenant in tenants_to_check:
        assert 'rabbitmq_user_{0}'.format(tenant) in mq_passwords

    logger.info('Editing security config file on the manager...')
    _edit_security_config(image_based_manager)

    logger.info('Editing hooks.conf file on the manager...')
    image_based_manager.put_remote_file_content(REMOTE_HOOKS_PATH, NEW_HOOKS)

    logger.info('Running `cfy_manager configure`...')
    image_based_manager.run_command(
        'cfy_manager configure --private-ip {0} --public-ip {1}'.format(
            image_based_manager.private_ip_address,
            image_based_manager.ip_address)
    )

    logger.info('Verifying certificates unchanged after configure...')
    new_cert = image_based_manager.get_remote_file_content(REMOTE_CERT_PATH)
    assert old_cert == new_cert

    logger.info('Validating security config file on the manager persists...')
    security_config = json.loads(
        image_based_manager.get_remote_file_content(REMOTE_CONF_PATH)
    )

    assert NEW_KEY in security_config
    assert security_config[NEW_KEY] == NEW_VALUE

    logger.info('Validating hooks.conf file unchanged after configure...')
    hooks_content = image_based_manager.get_remote_file_content(
        REMOTE_HOOKS_PATH)

    assert hooks_content == NEW_HOOKS

    logger.info('Validating MQ passwords unchanged after configure...')
    # We expect the command to fail if the password has changed or
    # if the any of the users weren't recreated in RMQ
    for mq_user, mq_password in mq_passwords.items():
        image_based_manager.run_command(
            AUTH_MQ_USER_CMD.format(user=mq_user, password=mq_password),
            use_sudo=True
        )


def _edit_security_config(manager):
    security_config = json.loads(
        manager.get_remote_file_content(REMOTE_CONF_PATH)
    )

    security_config[NEW_KEY] = NEW_VALUE

    manager.put_remote_file_content(
        REMOTE_CONF_PATH, json.dumps(security_config)
    )


def _get_mq_passwords(manager):
    manager.run_command(
        'sudo /opt/manager/env/bin/python {script}'.format(
            script=GET_MQ_PASSWORDS_CODE_PATH,
        )
    )
    mq_passwords = manager.get_remote_file_content(MQ_PASSWORDS_PATH)
    return json.loads(mq_passwords)
