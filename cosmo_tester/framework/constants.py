CLOUDIFY_TENANT_HEADER = 'Tenant'

SUPPORTED_RELEASES = [
    '5.1.0',
    '5.1.1',  # Keeping this version because here we started better versioning
    '5.1.4',
    '5.2.0',
    '5.2.7',
    '6.1.0',
    '6.2.0',
    '6.3.0',
    '6.3.2',
    '6.4.0',
    '6.4.1',
    'master',
]

SUPPORTED_FOR_RPM_UPGRADE = [
    version + '-ga'
    for version in SUPPORTED_RELEASES
    if not (version == 'master' or version.startswith('5.'))
]
