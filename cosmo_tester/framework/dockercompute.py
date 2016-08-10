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

from StringIO import StringIO

import fabric
import fabric.network
import fabric.api as ssh
import fabric.context_managers
import sh

from cloudify_cli.env import get_profile_context

from cosmo_tester.framework import testenv
from cosmo_tester.framework import util


def manager_setup():
    env = testenv.test_environment
    if not env.management_ip:
        return
    _install_docker_and_configure_image(env)
    _upload_dockercompute_plugin(env)


def _install_docker_and_configure_image(env):
    profile = get_profile_context()

    default_docker_host = 'fd://'
    docker_host = env.handler_configuration.get(
        'docker_host', default_docker_host)
    local_docker = env.handler_configuration.get('local_docker')
    docker_version = None
    if local_docker:
        from sh import docker
        try:
            docker_version = docker.version(
                '-f', '{{.Client.Version}}').stdout.strip()
        except sh.ErrorReturnCode as e:
            docker_version = e.stdout.strip()
    username = profile.manager_user
    with fabric.context_managers.settings(
            port=profile.manager_port,
            host_string=profile.manager_ip,
            user=username,
            key_filename=profile.manager_key):
        try:
            images = ssh.run('docker -H {0} images '
                             '--format "{{{{.Repository}}}}"'
                             .format(docker_host))
            if 'cloudify/centos-plain' not in images:
                raise RuntimeError
        except:
            workdir = '/root/dockercompute'
            ssh.put(util.get_resource_path('dockercompute/docker.repo'),
                    '/etc/yum.repos.d/docker.repo', use_sudo=True)
            commands = ['mkdir -p {0}'.format(workdir)]
            install_docker_command = 'yum install -y -q docker-engine'
            if docker_version:
                install_docker_command = '{}-{}'.format(install_docker_command,
                                                        docker_version)
            commands.append(install_docker_command)
            if docker_host == default_docker_host:
                commands += [
                    'usermod -aG docker {0}'.format(username),
                    'systemctl start docker',
                    'systemctl enable docker',
                    'systemctl status docker',
                ]
            ssh.sudo(' && '.join(commands))
            # Need to reset the connection so subsequent docker calls don't
            # need sudo
            fabric.network.disconnect_all()
            with fabric.context_managers.cd(workdir):
                ssh.put(util.get_resource_path('dockercompute/Dockerfile'),
                        'Dockerfile', use_sudo=True)
                ssh.sudo('docker -H {0} build -t cloudify/centos-plain:7 .'
                         .format(docker_host))
                if docker_host != default_docker_host:
                    docker_host_file_obj = StringIO(docker_host)
                    ssh.put(docker_host_file_obj,
                            'docker_host', use_sudo=True)


def _upload_dockercompute_plugin(env):
    client = env.rest_client
    docker_compute_plugin = client.plugins.list(
        package_name='cloudify-dockercompute-plugin',
        _include=['id']).items
    if docker_compute_plugin:
        return
    wagon_path = util.create_wagon(
        source_dir=util.get_resource_path('dockercompute/plugin'),
        target_dir=env._workdir)
    client.plugins.upload(wagon_path)
