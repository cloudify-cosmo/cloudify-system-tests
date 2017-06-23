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


REQUIRED_INFO = ('host', 'port', 'user', 'password', 'vhost', 'queue')


class FakeAgent(Process):

    def __init__(self, connection_info, agents, *args, **kwargs):
        super(FakeAgent, self).__init__(*args, **kwargs)
        self.agents = agents
        self.connection_info = connection_info

    def run(self):
        "The work that the fake agent shall do"
        with Connection(
            'amqp://{user}:{password}@{host}:{port}/{vhost}/'.format(
                **self.connection_info
                )) as amqp:
            with amqp.channel() as channel:
                producer = Producer(channel)

                while self.agents[self.connection_info['queue']]["run"]:
                    time.sleep(1)
                    print(self.agents)


manager = Manager()
agents = manager.dict()

app = Flask(__name__)


def start_agent(agent_name, connection_info):
    process = FakeAgent(connection_info, agents)
    agents[agent_name] = {
        'run': True,
        }
    process.start()


def stop_agent(agent_name, connection_info):
    agent = agents[agent_name]
    agent['run'] = False
    agents[agent_name] = agent


@app.route("/<queue>", methods=['POST', 'DELETE'])
def action(queue):
    connection_info = {
        k: v
        for (k, v) in request.form.items()
        if k in REQUIRED_INFO
        }

    if len(connection_info) != len(REQUIRED_INFO):
        response = jsonify({'message': 'invalid parameters'})
        response.status_code = 418
        return response

    agent_name = (
        connection_info['host'],
        connection_info['vhost'],
        connection_info['queue'],
        )

    {
        'POST': start_agent,
        'DELETE': stop_agent,
    }[request.method](agent_name, connection_info)

    return jsonify({'started': True})
