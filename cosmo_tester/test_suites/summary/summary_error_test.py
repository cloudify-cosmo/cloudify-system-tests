import pytest

from cloudify_rest_client.exceptions import CloudifyClientError


SUPPORTED_FIELDS = {
    'blueprints': [
        'tenant_name',
        'visibility',
    ],
    'deployments': [
        'blueprint_id',
        'tenant_name',
        'visibility',
        'site_name',
    ],
    'executions': [
        'status',
        'blueprint_id',
        'deployment_id',
        'workflow_id',
        'tenant_name',
        'visibility',
    ],
    'nodes': [
        'deployment_id',
        'tenant_name',
        'visibility',
    ],
    'node_instances': [
        'deployment_id',
        'node_id',
        'state',
        'host_id',
        'tenant_name',
        'visibility',
    ],
}


@pytest.mark.parametrize("summary_type", [
    "blueprints",
    "deployments",
    "executions",
    "nodes",
    "node_instances",
])
def test_bad_field_selected(prepared_manager, summary_type):
    """
        Confirm a helpful error message is returned if a bad field is selected
    """
    summary_endpoint = getattr(prepared_manager.client.summary, summary_type)
    try:
        summary_endpoint.get(_target_field='notafield')
        raise AssertionError(
            'Field notafield should not have been accepted by client for '
            '{endpoint}.'.format(endpoint=summary_type)
        )
    except CloudifyClientError as err:
        components = ['notafield', 'summary', 'Invalid']
        components.extend(SUPPORTED_FIELDS[summary_type])
        if not all(component in str(err) for component in components):
            raise AssertionError(
                '{endpoint} did not provide a helpful error message for '
                'an invalid field. Error message should have stated '
                'which field was invalid, and given a list of fields '
                'which were valid. Expected valid fields were: {valid}. '
                'Returned message was: {message}'.format(
                    endpoint=summary_type,
                    valid=', '.join(
                        SUPPORTED_FIELDS[summary_type]
                    ),
                    message=str(err),
                )
            )


@pytest.mark.parametrize("summary_type", [
    "blueprints",
    "deployments",
    "executions",
    "nodes",
    "node_instances",
])
def test_bad_subfield_selected(prepared_manager, summary_type):
    """
        Confirm a helpful error message is returned if a bad subfield is
        selected
    """
    summary_endpoint = getattr(prepared_manager.client.summary, summary_type)
    try:
        summary_endpoint.get(_target_field='tenant_name',
                             _sub_field='notafield')
        raise AssertionError(
            'Field notafield should not have been accepted by client for '
            '{endpoint}.'.format(endpoint=summary_type)
        )
    except CloudifyClientError as err:
        components = ['notafield', 'summary', 'Invalid']
        components.extend(SUPPORTED_FIELDS[summary_type])
        if not all(component in str(err) for component in components):
            raise AssertionError(
                '{endpoint} did not provide a helpful error message for '
                'an invalid field. Error message should have stated '
                'which field was invalid, and given a list of fields '
                'which were valid. Expected valid fields were: {valid}. '
                'Returned message was: {message}'.format(
                    endpoint=summary_type,
                    valid=', '.join(
                        SUPPORTED_FIELDS[summary_type]
                    ),
                    message=str(err),
                )
            )
