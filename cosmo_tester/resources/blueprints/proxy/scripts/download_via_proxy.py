from cloudify import ctx
import requests

error_message = ''
try:
    requests.get('https://example.com')
except Exception as e:
    error_message = str(e)
if 'proxy' not in error_message:
    ctx.abort_operation(
        'Expected the error to be caused by proxy, but was: {0}'
        .format(error_message)
    )
