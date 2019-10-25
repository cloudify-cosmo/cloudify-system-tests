########
# Copyright (c) 2019 Cloudify Platform Ltd. All rights reserved
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

from .test_hosts import (
    TestHosts,
    BootstrapBasedCloudifyManagers,
)


SKIP_SANITY = {'skip_sanity': 'true'}
DATABASE_SERVICES_TO_INSTALL = ['database_service']
QUEUE_SERVICES_TO_INSTALL = ['queue_service']
MANAGER_SERVICES_TO_INSTALL = ['manager_service']


@pytest.fixture(scope='module')
def image_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    hosts = TestHosts(
            cfy, ssh_key, module_tmpdir, attributes, logger, request=request)
    try:
        hosts.create()
        hosts.instances[0].use()
        yield hosts.instances[0]
    finally:
        hosts.destroy()


@pytest.fixture(scope='module')
def image_based_manager_without_plugins(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    hosts = TestHosts(
            cfy, ssh_key, module_tmpdir, attributes, logger, request=request,
            upload_plugins=False)
    try:
        hosts.create()
        hosts.instances[0].use()
        yield hosts.instances[0]
    finally:
        hosts.destroy()


@pytest.fixture(scope='module')
def bootstrap_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps a cloudify manager on a VM in rackspace OpenStack."""
    hosts = BootstrapBasedCloudifyManagers(
            cfy, ssh_key, module_tmpdir, attributes, logger)
    try:
        hosts.create()
        hosts.instances[0].use()
        yield hosts.instances[0]
    finally:
        hosts.destroy()
