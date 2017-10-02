#!/usr/bin/env python

import os

from cloudify import ctx
from cloudify.exceptions import NonRecoverableError
from cloudify_agent.installer.config.agent_config import (
    create_agent_config_and_installer,
    )


actions = {}


def action(func):

    @create_agent_config_and_installer
    def wrapper(*args, **kwargs):
        agent_config = kwargs['cloudify_agent']
        installer = kwargs['installer']

        return func(agent_config, installer)

    actions[func.__name__] = wrapper


@action
def create(agent_config, installer):
    installer.start_agent()


if __name__ == "__main__":
    try:
        action = actions[os.getenv('action')]
    except KeyError as e:
        ctx.logger.error('invalid action')
        raise NonRecoverableError(e)

    try:
        action()
    except Exception as e:
        ctx.logger.error(e)
        raise NonRecoverableError(e)
