########
# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
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


import pytest

from cosmo_tester.framework.util import (
    get_attributes,
    get_cli_package_url,
    get_resource_path,
)
from cosmo_tester.framework.test_hosts import (
    get_image,
    REMOTE_PRIVATE_KEY_PATH,
    TestHosts,
)


def get_linux_image_settings():
    attrs = get_attributes()
    return [
        (attrs.centos_7_image_name, attrs.centos_7_username,
         'rhel_centos_cli_package_url'),
        (attrs.ubuntu_14_04_image_name, attrs.ubuntu_14_04_username,
         'debian_cli_package_url'),
        (attrs.rhel_7_image_name, attrs.rhel_7_username,
         'rhel_centos_cli_package_url'),
    ]


@pytest.fixture(
    scope='module',
    params=get_linux_image_settings())
def linux_cli_tester(request, cfy, ssh_key, module_tmpdir, attributes,
                     logger, install_dev_tools=True):
    instances = [
        get_image('centos'),
        get_image('master'),
    ]

    instances[0].image_name = request.param[0]
    instances[0].username = request.param[1]

    cli_hosts = TestHosts(
        cfy, ssh_key, module_tmpdir,
        attributes, logger, instances=instances, request=request,
        upload_plugins=False,
    )
    cli_hosts.create()

    yield {
        'cli_hosts': cli_hosts,
        'username': instances[1].username,
        'url_key': request.param[2],
    }
    cli_hosts.destroy()


def test_cli_on_linux(linux_cli_tester, attributes):
    cli_host, manager_host = linux_cli_tester['cli_hosts'].instances

    local_script_path = get_resource_path(
        'scripts/linux-cli-test'
    )
    remote_script_path = '/tmp/linux-cli-test'

    cli_host.put_remote_file(
        remote_path=remote_script_path,
        local_path=local_script_path,
    )
    cli_host.run_command('chmod 500 {}'.format(remote_script_path))

    cli_host.run_command(
        '{script} {cli_url} {key} {mgr_pub} {mgr_priv} {mgr_os_user}'.format(
            script=remote_script_path,
            cli_url=get_cli_package_url(linux_cli_tester['url_key']),
            key=REMOTE_PRIVATE_KEY_PATH,
            mgr_pub=manager_host.ip_address,
            mgr_priv=manager_host.private_ip_address,
            mgr_os_user=linux_cli_tester['username'],
        )
    )
