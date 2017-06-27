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

from cloudify import ctx
from cloudify.decorators import operation
from cloudify.exceptions import NonRecoverableError
from cloudify_agent.installer.operations import init_agent_installer


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


@init_agent_installer
def get_connection_info(cloudify_agent, **kwargs):
    init_script = ctx.agent.init_script()

    env = {}
    for line in init_script.splitlines():
        _, _, export = line.strip().partition('export ')
        k, e, v = export.partition('=')
        if e:
            env[k] = v

    return {
        'host': env['CLOUDIFY_BROKER_IP'],
        'ssl_enabled': env['CLOUDIFY_BROKER_SSL_ENABLED'],
        'user': env['CLOUDIFY_BROKER_USER'],
        'password': env['CLOUDIFY_BROKER_PASS'],
        'vhost': env['CLOUDIFY_BROKER_VHOST'],
        'queue': env['CLOUDIFY_DAEMON_QUEUE'],
        'name': env['CLOUDIFY_DAEMON_NAME'],
        }


def send_message(host, port, action):
    connection_info = get_connection_info()

    response = {
        'start': requests.post,
        'stop': requests.delete,
    }[action](URL_TEMPLATE.format(
        fake_agent_host=host,
        port=port,
        host=connection_info.pop('host'),
        vhost=connection_info.pop('vhost'),
        queue=connection_info.pop('queue'),
        name=connection_info.pop('name'),
        ),
        data=connection_info)

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        raise NonRecoverableError(response, response.text)
