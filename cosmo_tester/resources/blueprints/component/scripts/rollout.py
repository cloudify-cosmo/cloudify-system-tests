from cloudify.workflows import ctx
from cloudify.workflows.tasks_graph import make_or_get_graph


# The make_or_get_graph decorator is a convenience facility.
# If a graph has already been created for this execution, then it is loaded from storage
# and the function itself is ignored. Otherwise, the function is invoked
# and the resulting graph is stored for future use.
@make_or_get_graph
def create_graph(ctx, parameter):
    graph = ctx.graph_mode()
    sequence = graph.sequence()
    # Iterate over all node instances of type "cloudify.nodes.SoftwareComponent"
    # and invoke the "update" and "commit" operations for each.
    for node_instance in ctx.node_instances:
        if node_instance.node.type == 'cloudify.nodes.SoftwareComponent':
            sequence.add(node_instance.execute_operation('maintenance.update'))
            sequence.add(node_instance.execute_operation('maintenance.commit'))

    return graph


ctx.logger.info("Rolling out application")
execution_graph = create_graph(ctx, None, name="rollout")
execution_graph.execute()
