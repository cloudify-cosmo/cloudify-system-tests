#!/usr/bin/env python

from cloudify import ctx

ctx.logger.info("Committing application")

# We determine whether the operation should fail or not, by inspecting
# the value of a runtime property called "fail_commit".
# If it is set to "True", then we fail the execution in a non-recoverable
# manner (i.e. this operation won't be automatically retried).
fail_commit = ctx.instance.runtime_properties.get('fail_commit', False)
if fail_commit:
    raise Exception("Asked to fail the commit operation")

ctx.logger.info("Committed application")
