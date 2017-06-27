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

import time
from multiprocessing import Manager, Process

from flask import Flask, jsonify, request
from kombu import Connection, Producer

from cloudify.constants import BROKER_PORT_SSL, BROKER_PORT_NO_SSL


QUEUE_INFO = ('host', 'vhost', 'queue', 'name')
EXTRA_INFO = ('ssl_enabled', 'user', 'password')


class FakeAgent(Process):

    def __init__(self, agent_name, connection_info, agents, *args, **kwargs):
        super(FakeAgent, self).__init__(*args, **kwargs)
        self.agents = agents
        self.agent_name = agent_name
        self.connection_info = connection_info

    def run(self):
        "The work that the fake agent shall do"
        port = (
                BROKER_PORT_SSL
                if self.connection_info['ssl_enabled'] else
                BROKER_PORT_NO_SSL
                )

        try:
            with Connection(
                'amqp://{user}:{password}@{host}:{port}/{vhost}/'.format(
                    port=port,
                    **self.connection_info
                    )) as amqp:
                with amqp.channel() as channel:
                    producer = Producer(channel)

                    entry = self.agents[self.queue_name]
                    entry['started'] = True
                    self.agents[self.queue_name] = entry

                    while self.agents[self.connection_info['queue']]["run"]:
                        time.sleep(1)
                        print(self.agents)
        except Exception as e:
            entry = self.agents[self.agent_name]
            entry['exception'] = e
            self.agents[self.agent_name] = entry
            raise


manager = Manager()
agents = manager.dict()

app = Flask(__name__)


def start_agent(agent_name, connection_info):
    process = FakeAgent(agent_name, connection_info, agents)
    agents[agent_name] = {
        'run': True,
        'started': False,
        }
    process.start()
    while not agents[agent_name]['started']:
        time.sleep(1)
        if not process.is_alive():
            raise RuntimeError(agents[agent_name]['exception'])


def stop_agent(agent_name, connection_info):
    agent = agents[agent_name]
    agent['run'] = False
    agents[agent_name] = agent


@app.route(
        "".join("/<{i}>".format(i=i) for i in QUEUE_INFO),
        methods=['POST', 'DELETE'])
def action(**kwargs):
    connection_info = {
        k: v
        for (k, v) in request.form.items()
        if k in EXTRA_INFO
        }

    if len(connection_info) != len(EXTRA_INFO):
        response = jsonify({'message': 'invalid parameters'})
        response.status_code = 418
        return response

    connection_info.update(kwargs)

    agent_name = tuple(connection_info[i] for i in QUEUE_INFO)

    {
        'POST': start_agent,
        'DELETE': stop_agent,
    }[request.method](agent_name, connection_info)

    return jsonify({'started': True})
