#!/bin/bash -e

BRANCH="CFY-1377-upgrade-3.1"

if [[ ! -d /tmp/docker_testing ]]; then
    mkdir /tmp/docker_testing
fi
cd /tmp/docker_testing

    wget "https://github.com/cloudify-cosmo/cloudify-docker-plugin/archive/${BRANCH}.tar.gz" -O docker.tar.gz
tar zxvf docker.tar.gz
cd "cloudify-docker-plugin-${BRANCH}"

${VIRTUALENV}/bin/pip install nose
${VIRTUALENV}/bin/nosetests docker_plugin/tests
