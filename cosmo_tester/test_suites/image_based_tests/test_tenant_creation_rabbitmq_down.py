import pytest

from cloudify_rest_client.exceptions import CloudifyClientError


def test_tenant_creation_no_rabbitmq(image_based_manager):
    image_based_manager.run_command(
        'systemctl stop cloudify-rabbitmq', use_sudo=True)

    with pytest.raises(CloudifyClientError):
        image_based_manager.client.tenants.create('badtenant')

    image_based_manager.run_command(
        'systemctl start cloudify-rabbitmq', use_sudo=True)

    # The tenant cannot have been properly created while rabbit was down, so
    # the tenant should not exist
    tenants = image_based_manager.client.tenants.list()
    tenant_names = [tenant['name'] for tenant in tenants.items]

    assert tenant_names == ['default_tenant']
