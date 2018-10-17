########
# Copyright (c) 2018 Cloudify Platform Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import json

from cosmo_tester.framework.fixtures import image_based_manager


manager = image_based_manager

REMOTE_CERT_PATH = '/etc/cloudify/ssl/cloudify_internal_ca_cert.pem'
REMOTE_CONF_PATH = '/opt/manager/rest-security.conf'
REMOTE_HOOKS_PATH = '/opt/mgmtworker/config/hooks.conf'
LIST_MQ_USERS_COMMAND = 'rabbitmqctl -n cloudify-manager@localhost list_users'

NEW_TENANT = 'new_tenant'
NEW_KEY = 'new_key'
NEW_VALUE = 'new_value'
NEW_HOOKS = 'new_hooks'


def test_cfy_manager_configure(manager, logger, tmpdir):
    manager.sync_local_code_to_manager()

    logger.info('Getting current CA cert from the manager...')
    old_cert = manager.get_remote_file_content(REMOTE_CERT_PATH)

    logger.info('Creating new tenant and validating RMQ user was created...')
    manager.client.tenants.create(NEW_TENANT)
    output = manager.run_command(LIST_MQ_USERS_COMMAND, use_sudo=True)
    assert NEW_TENANT in output

    logger.info('Editing security config file on the manager...')
    _edit_security_config(manager)

    logger.info('Editing hooks.conf file on the manager...')
    manager.put_remote_file_content(REMOTE_HOOKS_PATH, NEW_HOOKS)

    logger.info('Running `cfy_manager configure`...')
    manager.run_command('cfy_manager configure')

    logger.info('Verifying certificates unchanged after configure...')
    new_cert = manager.get_remote_file_content(REMOTE_CERT_PATH)
    assert old_cert == new_cert

    logger.info('Verifying RabbitMQ users recreated after configure...')
    output = manager.run_command(LIST_MQ_USERS_COMMAND, use_sudo=True)
    assert NEW_TENANT in output

    logger.info('Validating security config file on the manager persists...')
    security_config = json.loads(
        manager.get_remote_file_content(REMOTE_CONF_PATH)
    )

    assert NEW_KEY in security_config
    assert security_config[NEW_KEY] == NEW_VALUE

    logger.info('Validating hooks.conf file unchanged after configure...')
    hooks_content = manager.get_remote_file_content(REMOTE_HOOKS_PATH)

    assert hooks_content == NEW_HOOKS


def _edit_security_config(manager):
    security_config = json.loads(
        manager.get_remote_file_content(REMOTE_CONF_PATH)
    )

    security_config[NEW_KEY] = NEW_VALUE

    manager.put_remote_file_content(
        REMOTE_CONF_PATH, json.dumps(security_config)
    )
