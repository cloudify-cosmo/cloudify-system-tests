DEPLOYMENTS_PER_SITE = [
    {'site_name': 'site_1', 'deployments': 3},
    {'site_name': 'site_2', 'deployments': 2},
    {'site_name': 'site_3', 'deployments': 1}
]


def _assert_summary_equal(results, expected):
    assert len(results) == len(expected)
    for item in results:
        assert _sort_subfields(item) in expected, \
            '{0} not in {1}'.format(item, expected)


def _sort_subfields(summary_item):
    result_dict = {}
    for key, val in summary_item.items():
        if isinstance(val, list):
            if isinstance(val[0], dict):
                result_dict[key] = val
                sort_key = u'deployment_id' if u'deployment_id' in val[0] \
                    else u'workflow_id'
                result_dict[key].sort(key=lambda x: x[sort_key], reverse=False)
            else:
                result_dict[key] = sorted(val)
        elif isinstance(val, dict):
            result_dict[key] = _sort_subfields(val)
        else:
            result_dict[key] = val
    return result_dict
