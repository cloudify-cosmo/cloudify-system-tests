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
import time
from multiprocessing import Manager, Process

from celery import Celery, bootsteps
from flask import Flask, jsonify, request
from kombu import Consumer, Exchange, Queue

from cloudify.constants import BROKER_PORT_SSL, BROKER_PORT_NO_SSL


QUEUE_INFO = ('host', 'vhost', 'queue', 'name')
EXTRA_INFO = ('ssl_enabled', 'user', 'password')


WORKER_CONFIG = {
    'mim_workers': 0,
    'max_workers': 5,
    }


class PretendItsDone(bootsteps.ConsumerStep):

    @property
    def queue(self):
        raise NotImplementedError(
            'the queue must be provided before using this bootstep')

    def get_consumers(self, channel):
        return [Consumer(
            channel,
            queues=[type(self).queue],
            callbacks=[self.handle_message],
            accept=['json'],
            )]

    def handle_message(self, body, message):
        print('Received: {0!r}'.format(body))
        message.ack()


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
        connect_string = (
            'amqp://{user}:{password}@{host}:{port}/{vhost}'.format(
                port=port,
                **self.connection_info
            ))

        worker_args = [
            "--events",
            "-Q", self.connection_info['queue'],
            "--hostname", self.connection_info['name'],
            "--autoscale={{ max_workers }},{{ min_workers }}".format(
                WORKER_CONFIG),
            "--maxtasksperchild=10",
            "-Ofair",
            "--without-gossip",
            "--without-mingle",
            "--config=cloudify.broker_config",
            "--include=cloudify.dispatch",
            "--with-gate-keeper",
            "--gate-keeper-bucket-size={max_workers}".format(
                WORKER_CONFIG),
            "--with-logging-server",
            "--logging-server-logdir={workdir}".format(os.path.join(
                os.path.expanduser('~'), 'agent_logs', *self.agent_name)),
            "--heartbeat-interval=2",
            ]

        try:
            queue = Queue(
                self.connection_info['queue'],
                Exchange('cloudify-events'),
                )
            # Adding the queue as a class attribute because celery's bootsteps
            # API wants to be given a class, not an instance.
            PretendItsDone.queue = queue

            with Celery('', broker=connect_string) as app:

                app.steps['consumer'].add(PretendItsDone)

                try:
                    worker = app.worker_main(argv=worker_args)

                    with amqp.channel() as channel:
                        producer = Producer(channel)

                        entry = self.agents[self.agent_name]
                        entry['started'] = True
                        self.agents[self.agent_name] = entry

                        while self.agents[self.agent_name]["run"]:
                            time.sleep(1)
                            print(self.agents)
                finally:
                    worker.close()

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
