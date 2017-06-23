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

import json

import requests

from cloudify import ctx
from cloudify.decorators import operation
from cloudify_agent.installer import AgentInstaller
from cloudify_agent.installer.operations import init_agent_installer


URL_TEMPLATE = 'http://{host}:{port}/{queue}'


@operation
def start(host, port, **kwargs):
    ""
    ctx.logger.info(kwargs)
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
def get_connection_info(cloudify_agent):
    installer = AgentInstaller(cloudify_agent)
    env = installer._create_agent_env()
    return {
        'host': env.CLOUDIFY_BROKER_IP,
        'port': env.CLOUDIFY_REST_PORT,
        'user': env.CLOUDIFY_BROKER_USER,
        'password': env.CLOUDIFY_BROKER_PASS,
        'vhost': env.CLOUDIFY_BROKER_VHOST,
        'queue': env.CLOUDIFY_DAEMON_QUEUE,
        'name': env.CLOUDIFY_DAEMON_NAME,
        }


def send_message(host, port, action):
    connection_info = get_connection_info()

    {
        'start': requests.post,
        'stop': requests.delete,
    }[action](URL_TEMPLATE.format(
        host=host,
        port=port,
        queue=connection_info['name']
        ),
        params=connection_info)
