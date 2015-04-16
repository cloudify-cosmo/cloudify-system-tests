########
# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
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

import fabric.api


def create(use_sudo=False):
    sudo = 'sudo' if use_sudo else ''
    install_docker_cmd = '{0} yum install -y docker && ' \
                         '{0} yum update -y device-mapper-libs && ' \
                         '{0} service docker restart'.format(sudo)
    fabric.api.run(install_docker_cmd)
