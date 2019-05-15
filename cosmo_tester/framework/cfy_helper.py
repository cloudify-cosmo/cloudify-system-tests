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


USER_NAME = "test_user"
USER_PASS = "testuser123"
TENANT_NAME = "tenant"


def create_secrets(cfy, logger, attributes, manager1, visibility=TENANT_NAME):
    logger.info('Creating secret agent_user as blueprint input')
    cfy.secrets.create('agent_user', '-s', attributes.default_linux_username,
                       visibility=visibility)

    logger.info('Creating secret agent_private_key_path as blueprint input')
    cfy.secrets.create('agent_private_key_path', '-s',
                       manager1.remote_private_key_path,
                       visibility=visibility)

    logger.info('Creating secret host_ip as blueprint input')
    cfy.secrets.create('host_ip', '-s', manager1.ip_address,
                       visibility=visibility)


def create_and_add_user_to_tenant(cfy,
                                  logger,
                                  username=USER_NAME,
                                  userpass=USER_PASS,
                                  tenant_name=TENANT_NAME):
    logger.info('Creating new user')
    cfy.users.create(username, '-p', userpass)

    logger.info('Adding user to tenant')
    cfy.tenants('add-user', username, '-t', tenant_name, '-r', 'user')


def set_admin_user(cfy, manager, logger):
    manager.use()
    logger.info('Using manager `{0}`'.format(manager.ip_address))
    cfy.profiles.set('-u', 'admin', '-p', 'admin', '-t', 'default_tenant')
