import argparse
# While the config is yaml, using json to dump the examples of it gives a
# cleaner output
import json
import os
import sys

from cosmo_tester.framework.config import load_config
from cosmo_tester.framework.logger import get_logger


def show_schema(schema,
                generate_sample_config=False,
                include_defaults=False,
                indent='',
                raw_config=None):
    raw_config = raw_config or {}
    output = []
    sorted_config_entries = schema.keys()
    sorted_config_entries = [
        entry for entry in sorted_config_entries
        if isinstance(schema[entry], dict)
    ]
    sorted_config_entries.sort()

    namespaces = [
        entry for entry in sorted_config_entries
        if schema[entry].get('.is_namespace', False)
    ]
    root_config_entries = [
        entry for entry in sorted_config_entries
        if entry not in namespaces
    ]

    for config_entry in root_config_entries:
        details = schema[config_entry]
        template = '{indent}{entry}: {value} # {description}'
        if generate_sample_config:
            if config_entry in raw_config:
                output.append(template.format(
                    indent=indent,
                    entry=config_entry,
                    value=raw_config[config_entry],
                    description=details['description'],
                ))
            elif 'default' in details.keys():
                if include_defaults:
                    output.append(template.format(
                        indent=indent,
                        entry=config_entry,
                        value=json.dumps(details['default']),
                        description=details['description'],
                    ))
            else:
                output.append(template.format(
                    indent=indent,
                    entry=config_entry,
                    value='',
                    description=details['description'],
                ))
        else:
            line = '{entry}: {description}'
            if 'default' in schema[config_entry].keys():
                line = line + ' (Default: {default})'
            line = line.format(
                entry=config_entry,
                description=details['description'],
                default=json.dumps(details.get('default')),
            )
            output.append(indent + line)

    for namespace in namespaces:
        namespace_output = show_schema(
            schema[namespace],
            generate_sample_config,
            include_defaults,
            indent + '  ',
            raw_config=raw_config.get(namespace, {}),
        )
        if namespace_output:
            output.append(indent + namespace + ':')
            output.append(namespace_output)

    return '\n'.join(output)


def apply_platform_config(logger, config, platform):
    config.raw_config['target_platform'] = platform
    if platform == 'openstack':
        config.raw_config['openstack'] = {}
        target = config.raw_config['openstack']
        target['username'] = os.environ["OS_USERNAME"]
        target['password'] = os.environ["OS_PASSWORD"]
        target['tenant'] = (
            os.environ.get("OS_TENANT_NAME")
            or os.environ['OS_PROJECT_NAME']
        )
        target['url'] = os.environ["OS_AUTH_URL"]
        target['region'] = os.environ.get("OS_REGION_NAME", "RegionOne")


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Tool for working with test configs.'
        ),
    )

    subparsers = parser.add_subparsers(help='Action',
                                       dest='action')

    validate_args = subparsers.add_parser('validate',
                                          help='Validate the config.')
    validate_args.add_argument(
        '-c', '--config-location',
        help='The config file to validate.',
        default='test_config.yaml',
    )

    subparsers.add_parser('schema',
                          help='Print the schema.')

    generate_args = subparsers.add_parser('generate',
                                          help='Generate sample config.')
    generate_args.add_argument(
        '-i', '--include-defaults',
        help=(
            'Include entries with default values. '
            'This will result in a much longer config, most of which will '
            'not be required, but will allow for easy modification of any '
            'settings.'
        ),
        action='store_true',
        default=False
    )
    generate_args.add_argument(
        '-p', '--platform',
        help=(
            'Generate the initial config including values for the specified '
            'target platform. For platform configuration to be properly '
            "generated, you should have that platform's default way of "
            'authenticating prepared, e.g. ". openstackrc".'
        ),
    )

    args = parser.parse_args()

    logger = get_logger('conf_cli')

    if args.action == 'validate':
        # We validate on loading, so simply attempting to load the config with
        # the config supplied by the user will validate it
        load_config(logger, args.config_location)
    elif args.action == 'schema':
        config = load_config(logger, validate=False)
        print(show_schema(config.schema, False))
    elif args.action == 'generate':
        config = load_config(logger, validate=False)
        if args.platform:
            apply_platform_config(logger, config, args.platform)
            if not config.check_config_is_valid(fail_on_missing=False):
                sys.exit(1)
        print(show_schema(config.schema,
                          generate_sample_config=True,
                          include_defaults=args.include_defaults,
                          raw_config=config.raw_config))


if __name__ == '__main__':
    main()
