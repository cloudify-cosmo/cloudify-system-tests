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

import requests

from cloudify.decorators import operation
from cloudify.exceptions import NonRecoverableError
from cloudify_agent.installer.config.agent_config import (
    create_agent_config_and_installer,
    )


URL_TEMPLATE = 'http://{fake_agent_host}:{port}/{host}/{vhost}/{queue}/{name}'


@operation
def start(host, port, **kwargs):
    ""
    send_message(
        host,
        port,
        'start',
        )


@operation
def stop(host, port, **kwargs):
    ""
    send_message(
        host,
        port,
        'stop',
        )


@create_agent_config_and_installer(validate_connection=False)
def send_message(host, port, action, **kwargs):
    agent_config = kwargs['cloudify_agent']

    response = {
        'start': requests.post,
        'stop': requests.delete,
    }[action](URL_TEMPLATE.format(
        fake_agent_host=host,
        port=port,
        host=agent_config['broker_ip'],
        vhost=agent_config['broker_vhost'],
        queue=agent_config['queue'],
        name=agent_config['name'],
        ),
        data=agent_config)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        raise NonRecoverableError(response, response.text)
