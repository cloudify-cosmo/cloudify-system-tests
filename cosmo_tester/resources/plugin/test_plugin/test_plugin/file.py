import os
from cloudify.decorators import operation


@operation(resumable=True)
def create(ctx):
    """Create test file with contents as defined by node properties."""
    path = ctx.node.properties['path'] + '_' + ctx.instance.id
    content = ctx.node.properties['content']

    ctx.logger.info('Creating {path} with contents: {content}'.format(
        path=path,
        content=content,
    ))
    with open(path, 'w') as fh:
        fh.write(content)


@operation(resumable=True)
def delete(ctx):
    """Delete the test file."""
    path = ctx.node.properties['path'] + '_' + ctx.instance.id

    ctx.logger.info('Deleting {path}'.format(path=path))
    os.unlink(path)
