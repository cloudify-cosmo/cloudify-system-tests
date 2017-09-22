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

import os
from subprocess import check_output, Popen, CalledProcessError

from cloudify.decorators import operation
from cloudify.exceptions import NonRecoverableError


@operation
def start_server():
    # Install
    try:
        check_output(['virtualenv', 'server_env'])
    except CalledProcessError as e:
        raise NonRecoverableError(e)

    # Run
    env = os.environ.copy()
    env['FLASK_APP'] = ('server_env/lib/python2.7/site-packages/'
                        'cloudify_fake_agent/server.py'
                        )

    Popen(
            ['flask', 'run', '--port', 5566],
            )
