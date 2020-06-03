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

MOM_PLUGIN_REPO_PATH = 'cloudify-cosmo/cloudify-spire-plugin'
MOM_PLUGIN_VERSION = '3.2.4'
MOM_PLUGIN_RELEASE_NAME = '{0}'.format(MOM_PLUGIN_VERSION)
MOM_PLUGIN_WGN_NAME = 'cloudify_spire_plugin-{0}-py27-none-' \
                      'linux_x86_64-centos-Core.wgn'.format(
                           MOM_PLUGIN_VERSION)
MOM_PLUGIN_WGN_URL = 'https://github.com/cloudify-cosmo/' \
                     'cloudify-spire-plugin/releases/download/' \
                     '{0}/cloudify_spire_plugin-{0}-py27-none-' \
                     'linux_x86_64-centos-Core.wgn'.format(MOM_PLUGIN_VERSION)  # NOQA
MOM_PLUGIN_YAML_URL = 'https://github.com/cloudify-cosmo/' \
                      'cloudify-spire-plugin/releases/download/' \
                      '{0}/plugin.yaml'.format(MOM_PLUGIN_VERSION)  # NOQA

OS_WGN_FILENAME_TEMPLATE = 'cloudify_openstack_plugin-{0}-py27-none-linux_x86_64-centos-Core.wgn'  # NOQA
OS_YAML_URL_TEMPLATE = 'https://raw.githubusercontent.com/cloudify-cosmo/cloudify-openstack-plugin/{0}/plugin.yaml'  # NOQA
OS_WGN_URL_TEMPLATE = 'http://repository.cloudifysource.org/cloudify/wagons/cloudify-openstack-plugin/{0}/{1}'  # NOQA

# This version of the plugin is used by the mom blueprint
OS_PLUGIN_VERSION = '3.2.8'
OS_PLUGIN_WGN_FILENAME = OS_WGN_FILENAME_TEMPLATE.format(OS_PLUGIN_VERSION)
OS_PLUGIN_WGN_URL = OS_WGN_URL_TEMPLATE.format(OS_PLUGIN_VERSION,
                                               OS_PLUGIN_WGN_FILENAME)
OS_PLUGIN_YAML_URL = OS_YAML_URL_TEMPLATE.format(OS_PLUGIN_VERSION)

UTILITIES_PLUGIN_VERSION = '1.15.0'
UTIL_PLUGIN_WGN_URL = 'http://repository.cloudifysource.org/cloudify/wagons/' \
                      'cloudify-utilities-plugin/{0}/' \
                      'cloudify_utilities_plugin-{0}-py27-' \
                      'none-linux_x86_64-centos-Core.wgn'.format(
                          UTILITIES_PLUGIN_VERSION)
UTIL_PLUGIN_YAML_URL = 'http://www.getcloudify.org/spec/' \
                       'utilities-plugin/{0}/plugin.yaml'.format(
                           UTILITIES_PLUGIN_VERSION)

ANSIBLE_PLUGIN_VERSION = '2.7.0'
ANSIBLE_PLUGIN_WGN_URL = 'http://repository.cloudifysource.org/cloudify/' \
                         'wagons/cloudify-ansible-plugin/{0}/' \
                         'cloudify_ansible_plugin-{0}-py27-' \
                         'none-linux_x86_64-centos-Core.wgn'.format(
                             ANSIBLE_PLUGIN_VERSION)
ANSIBLE_PLUGIN_YAML_URL = 'http://www.getcloudify.org/spec/' \
                          'ansible-plugin/{0}/plugin.yaml'.format(
                              ANSIBLE_PLUGIN_VERSION)

# The version of the OS plugin used by Hello World Example
HW_OS_PLUGIN_VERSION = '3.2.8'
HW_OS_WGN_FILENAME = OS_WGN_FILENAME_TEMPLATE.format(HW_OS_PLUGIN_VERSION)
HW_OS_PLUGIN_WGN_URL = OS_WGN_URL_TEMPLATE.format(HW_OS_PLUGIN_VERSION,
                                                  HW_OS_WGN_FILENAME)
HW_OS_PLUGIN_YAML_URL = OS_YAML_URL_TEMPLATE.format(HW_OS_PLUGIN_VERSION)

HELLO_WORLD_URL = 'https://github.com/cloudify-community/blueprint-examples/releases/download/5.0.0-1/hello-world-example.zip'  # NOQA
HELLO_WORLD_BP = 'hello_world_bp'
HELLO_WORLD_DEP = 'hello_world_dep'

TENANT_1 = 'tenant_1'
TENANT_2 = 'tenant_2'

FIRST_DEP_INDICATOR = '0'
SECOND_DEP_INDICATOR = '1'

CENTRAL_MANAGER_SNAP_ID = 'snapshot_id'

INSTALL_RPM_PATH = '/etc/cloudify/cloudify-manager-install.rpm'
HW_OS_PLUGIN_WGN_PATH = '/etc/cloudify/{0}'.format(HW_OS_WGN_FILENAME)
HW_OS_PLUGIN_YAML_PATH = '/etc/cloudify/plugin.yaml'

SECRET_STRING_KEY = 'test_secret_from_string'
SECRET_STRING_VALUE = 'test_secret_value'
SECRET_FILE_KEY = 'test_secret_from_file'

HW_BLUEPRINT_ZIP_PATH = '/etc/cloudify/hello-world-example.zip'

SCRIPT_SH_PATH = '/etc/cloudify/script_1.sh'
SCRIPT_PY_PATH = '/etc/cloudify/script_2.py'

SSH_KEY_TMP_PATH = '/etc/cloudify/private.key'
PUB_KEY_TMP_PATH = '/etc/cloudify/public.key'
OS_CONFIG_TMP_PATH = '/tmp/openstack_config.json'

PY_SCRIPT = '''#!/usr/bin/env python
print 'Running a python script!'
'''
