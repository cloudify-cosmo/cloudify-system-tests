DEPLOYMENTS_PER_SITE = [
    {'site_name': 'site_1', 'deployments': 3},
    {'site_name': 'site_2', 'deployments': 2},
    {'site_name': 'site_3', 'deployments': 1}
]


def _assert_summary_equal(results, expected):
    assert len(results) == len(expected)
    for item in results:
        assert item in expected, '{0} not in {1}'.format(item, expected)
