import time
from cloudify.decorators import operation


@operation(resumable=True)
def wait_1min(ctx, **kwargs):
    time.sleep(60)
