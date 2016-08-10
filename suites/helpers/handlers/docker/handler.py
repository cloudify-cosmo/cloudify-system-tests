########
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys

import sh
import yaml

from cosmo_tester.framework import dockercompute
from cosmo_tester.framework.handlers import BaseHandler
from cosmo_tester.framework.handlers import BaseCleanupContext


def bake(cmd):
    return cmd.bake(_err_to_out=True,
                    _out=lambda l: sys.stdout.write(l),
                    _tee=True)


docl = bake(sh.docl)


class DockerCleanupContext(BaseCleanupContext):

    def cleanup(self):
        docl.clean()

    @classmethod
    def clean_all(cls, env):
        docl.clean()


class DockerHandler(BaseHandler):

    CleanupContext = DockerCleanupContext

    def before_bootstrap(self, manager_blueprint_path, inputs_path):
        with open(inputs_path) as f:
            previous_inputs = yaml.safe_load(f)
        docl.prepare(inputs_output=inputs_path)
        with open(inputs_path) as f:
            current_inputs = yaml.safe_load(f)
        final_inputs = previous_inputs
        final_inputs.update(current_inputs)
        with open(inputs_path, 'w') as f:
            yaml.safe_dump(final_inputs, f)

    def after_bootstrap(self, provider_context):
        dockercompute.manager_setup()

    def after_teardown(self):
        # created container is cleaned by the CleanContext.clean method
        pass


handler = DockerHandler
