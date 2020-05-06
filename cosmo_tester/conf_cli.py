import argparse
# While the config is yaml, using json to dump the examples of it gives a
# cleaner output
import json

from cosmo_tester.framework.config import (
    load_config,
    validate_config,
)
from cosmo_tester.framework.logger import get_logger


def show_schema(schema,
                generate_sample_config=False,
                include_defaults=False,
                indent=''):
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
        if generate_sample_config:
            if 'default' in details.keys():
                if include_defaults:
                    output.append(indent + '{entry}: {default}'.format(
                        entry=config_entry,
                        default=json.dumps(details['default'])
                    ))
            else:
                output.append(indent + '{entry}: '.format(entry=config_entry))
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
        )
        if namespace_output:
            output.append(indent + namespace + ':')
            output.append(namespace_output)
    return '\n'.join(output)


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

    args = parser.parse_args()

    logger = get_logger('conf_cli')

    if args.action == 'validate':
        config = load_config(logger, args.config_location)
        validate_config(config, logger)
    elif args.action == 'schema':
        config = load_config(logger)
        print(show_schema(config.schema, False))
    elif args.action == 'generate':
        config = load_config(logger)
        print(show_schema(config.schema,
                          generate_sample_config=True,
                          include_defaults=args.include_defaults))
