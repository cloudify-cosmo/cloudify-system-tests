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
import sys
import time
from multiprocessing import Manager, Process
from SocketServer import StreamRequestHandler, TCPServer

from kombu import Connection, Producer


class FakeAgent(Process):

    def __init__(self, instance, connection_info, agents, *args, **kwargs):
        super(FakeAgent, self).__init__(*args, **kwargs)
        self.instance = instance
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

                while self.agents[self.instance['id']]["run"]:
                    time.sleep(1)
                    print(self.agents)


class FakeAgentPool(object):

    def __init__(self):

        class FakeAgentHandler(StreamRequestHandler):
            def handle(inner_self):
                data = json.loads(inner_self.rfile.read().strip())

                {
                    'start': self.start_agent,
                    'stop': self.stop_agent,
                }[data['action']](data["instance"], data["connection_info"])

        self.handler = FakeAgentHandler

        self.manager = Manager()
        self.agents = self.manager.dict()

    def start_agent(self, instance, connection_info):
        process = FakeAgent(instance, connection_info, self.agents)
        self.agents[instance["id"]] = {
            'run': True,
            }
        process.start()

    def stop_agent(self, instance, *_):
        agent = self.agents[instance['id']]
        agent['run'] = False
        self.agents[instance['id']] = agent


class FakeAgentServer(TCPServer):
    allow_reuse_address = True


if __name__ == '__main__':
    pool = FakeAgentPool()

    server = FakeAgentServer((sys.argv[1], 5566), pool.handler)

    server.serve_forever()
