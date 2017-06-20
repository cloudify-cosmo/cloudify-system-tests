########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
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

from retrying import retry


@retry(stop_max_attempt_number=10, wait_fixed=5000)
def assert_snapshot_created(snapshot_id, client):
    snapshot = client.snapshots.get(snapshot_id)
    assert snapshot.status == 'created', 'Snapshot not in created status'


@retry(stop_max_attempt_number=6, wait_fixed=5000)
def assert_restore_workflow_terminated(execution_id, client, logger):
    logger.info('Getting restore workflow execution.. [id=%s]', execution_id)
    execution = client.executions.get(execution_id)
    logger.info('- execution.status = %s', execution.status)
    assert execution.status == 'terminated'
