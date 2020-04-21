import time


def wait(ctx):
    """Wait for a while when creating this node."""
    time.sleep(ctx.node.properties['delay'])
