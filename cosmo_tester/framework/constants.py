CLOUDIFY_TENANT_HEADER = 'Tenant'

SUPPORTED_RELEASES = [
    '5.0.5',
    '5.1.0',
    '5.1.1',
    '5.1.2',
    '5.1.3',
    '5.1.4',
    '5.2.0',
    '5.2.1',
    '6.0.0',
    'master',
]

SUPPORTED_FOR_RPM_UPGRADE = [
    version + '-ga'
    for version in SUPPORTED_RELEASES
    if version not in ('master', '5.0.5', '5.1.0')
]
