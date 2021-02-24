import time
from cloudify.decorators import operation


@operation(resumable=True)
def wait(ctx):
    """Wait for a while when creating this node."""
    time.sleep(ctx.node.properties['delay'])
