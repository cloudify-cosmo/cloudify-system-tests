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

MOM_PLUGIN_VERSION = '1.5.6'
MOM_PLUGIN_WGN_URL = 'https://github.com/Cloudify-PS/manager-of-managers/releases/download/v{0}/cloudify_manager_of_managers-{0}-py27-none-linux_x86_64.wgn'.format(MOM_PLUGIN_VERSION)  # NOQA
MOM_PLUGIN_YAML_URL = 'https://github.com/Cloudify-PS/manager-of-managers/releases/download/v{0}/cmom_plugin.yaml'.format(MOM_PLUGIN_VERSION)  # NOQA

# This version of the plugin is used by the mom blueprint
OS_PLUGIN_VERSION = '2.12.0'
OS_PLUGIN_WGN_FILENAME = 'cloudify_openstack_plugin-{0}-py27-none-linux_x86_64-centos-Core.wgn'.format(OS_PLUGIN_VERSION)  # NOQA
OS_PLUGIN_WGN_URL = 'http://repository.cloudifysource.org/cloudify/wagons/cloudify-openstack-plugin/{0}/{1}'.format(OS_PLUGIN_VERSION, OS_PLUGIN_WGN_FILENAME)  # NOQA
OS_PLUGIN_YAML_URL = 'http://www.getcloudify.org/spec/openstack-plugin/{0}/plugin.yaml'.format(OS_PLUGIN_VERSION)  # NOQA

# Using 2.0.1 because this is what the hello world blueprint is using
OS_201_PLUGIN_WGN_URL = 'http://repository.cloudifysource.org/cloudify/wagons/cloudify-openstack-plugin/2.0.1/cloudify_openstack_plugin-2.0.1-py27-none-linux_x86_64-centos-Core.wgn'  # NOQA
OS_201_PLUGIN_YAML_URL = 'http://www.getcloudify.org/spec/openstack-plugin/2.0.1/plugin.yaml'  # NOQA

HELLO_WORLD_URL = 'https://github.com/cloudify-cosmo/cloudify-hello-world-example/archive/4.5.zip'  # NOQA

TENANT_1 = 'tenant_1'
TENANT_2 = 'tenant_2'

FIRST_DEP_INDICATOR = '0'
SECOND_DEP_INDICATOR = '1'

TIER_2_SNAP_ID = 'snapshot_id'

INSTALL_RPM_PATH = '/etc/cloudify/cloudify-manager-install.rpm'
PLUGIN_WGN_PATH = '/etc/cloudify/{0}'.format(OS_PLUGIN_WGN_FILENAME)
PLUGIN_YAML_PATH = '/etc/cloudify/plugin.yaml'

SECRET_STRING_KEY = 'test_secret_from_string'
SECRET_STRING_VALUE = 'test_secret_value'
SECRET_FILE_KEY = 'test_secret_from_file'

BLUEPRINT_ZIP_PATH = '/etc/cloudify/cloudify-hello-world-example.zip'

SCRIPT_SH_PATH = '/etc/cloudify/script_1.sh'
SCRIPT_PY_PATH = '/etc/cloudify/script_2.py'

SH_SCRIPT = '''#!/usr/bin/env bash
echo "Running a bash script!"
'''

PY_SCRIPT = '''#!/usr/bin/env python
print 'Running a python script!'
'''