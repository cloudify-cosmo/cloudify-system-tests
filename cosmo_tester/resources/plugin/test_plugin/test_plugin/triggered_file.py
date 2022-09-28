import os
from cloudify.decorators import operation
from time import sleep


@operation(resumable=True)
def create(ctx):
    """Create a file, wait for another file to be created by an external
    process, then put a runtime property on the instance.
    """
    wait_path = ctx.node.properties['path'] + '_wait'

    ctx.logger.info('Creating %s', wait_path)
    with open(wait_path, 'w') as fh:
        fh.write('')

    trigger_path = ctx.node.properties['path'] + '_trigger'
    while not os.path.exists(trigger_path):
        ctx.logger.info('Waiting for %s to exist', trigger_path)
        sleep(10)
    ctx.logger.info('%s exists, setting flag', trigger_path)

    ctx.instance.runtime_properties['done'] = True
    ctx.logger.info('Flag set.')


@operation(resumable=True)
def delete(ctx):
    """Delete the test file."""
    wait_path = ctx.node.properties['path'] + '_wait'
    trigger_path = ctx.node.properties['path'] + '_trigger'

    for path in wait_path, trigger_path:
        if os.path.exists(path):
            ctx.logger.info('Deleting %s', path)
            os.unlink(path)
        else:
            ctx.logger.info('%s does not exist, skipping', path)
