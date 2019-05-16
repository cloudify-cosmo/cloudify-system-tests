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

from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)
from cosmo_tester.framework.cfy_helper import (
    set_admin_user,
    create_secrets
)

USER_NAME = "test_user"
USER_PASS = "testuser123"
TENANT_NAME = "tenant"


def test_distributed_installation_scenario(distributed_installation,
                                           cfy,
                                           logger,
                                           tmpdir,
                                           attributes,
                                           distributed_nodecellar):
    manager = distributed_installation.manager
    set_admin_user(cfy, manager, logger)

    # Creating secrets
    create_secrets(cfy, logger, attributes, manager, visibility='global')

    distributed_nodecellar.upload_and_verify_install()

    snapshot_id = 'SNAPSHOT_ID'
    create_snapshot(manager, snapshot_id, attributes, logger)

    # Restore snapshot
    logger.info('Restoring snapshot')
    restore_snapshot(manager, snapshot_id, cfy, logger, force=True)

    distributed_nodecellar.uninstall()
