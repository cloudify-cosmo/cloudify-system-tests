from collections import Mapping
import pkg_resources
import yaml

import os
import sys


class SchemaError(Exception):
    pass


class NotSet(object):
    pass


class NameSpace(Mapping):
    def __init__(self, config, raw_config):
        self._config = config
        self.raw_config = raw_config

    def __getitem__(self, item):
        if item in self._config:
            return self._config[item]
        else:
            if item in self.raw_config:
                raise KeyError(
                    'Config entry {key} was supplied but was not in the '
                    'schema. Please update the schema to use this config '
                    'entry.'.format(key=item)
                )
            else:
                raise KeyError(
                    'Config entry {key} was not supplied and is not in '
                    'schema.'.format(key=item)
                )

    def __iter__(self):
        return iter(self._config)

    def __len__(self):
        return len(self._config)

    def copy(self):
        return self._config.copy()


# Couldn't this all be a lot simpler?
# Yes.
# However, when we've gone for simpler approaches in the past we invariably
# end up with all sorts of weird and wonderful things happening, such as:
#   - Configuration entries created with unclear names and unclear utility.
#   - Configuration entries being added within the test framework run, to be
#     consumed elsewhere within that run, which you can only know exist if
#     you already knew to look.
#   - Configuration entries that need to exist, but don't, meaning that you
#     get to wait 10 minutes for VMs to be deployed before the test fails
#     due to not having a configuration entry it required.
# Until such time as we can all be uplifted as perfect machines, this config
# approach should make it hard to do the wrong thing.
# Now we just need to also make it easy to do the right thing!
class Config(NameSpace):
    def __init__(self, config_file, config_schema_files, logger):
        self._logger = logger
        self.schema = {}
        self.raw_config = {}
        self._cached_config = None

        # Load all initially supplied schemas
        for schema in config_schema_files:
            self._update_schema(schema)
        # We'll be pretty useless if we allow no config
        if len(self.schema) == 0:
            raise SchemaError('No valid config entries loaded from schemas.')

        # Load config
        if config_file:
            self._update_config(config_file)

    def _update_config(self, config_file):
        with open(config_file) as config_handle:
            raw_config = yaml.load(config_handle)
        self.raw_config.update(raw_config)

    def _update_schema(self, schema_file):
        with open(schema_file) as schema_handle:
            schema = yaml.load(schema_handle)

        namespace = None
        if 'namespace' in schema:
            namespace = schema['namespace']
            if namespace in self.schema:
                if not self.schema[namespace]['.is_namespace']:
                    raise SchemaError(
                        'Attempted to define namespace {namespace} but this '
                        'is already a configuration entry!'.format(
                            namespace=namespace,
                        )
                    )
            else:
                self.schema[namespace] = {'.is_namespace': True}
            schema.pop('namespace')

        # Make sure the schema is entirely valid- every entry must have a
        # description
        healthy_schema = True
        for key, value in schema.items():
            display_key = key
            if namespace is not None:
                display_key = '.'.join([namespace, key])
            if '.' in key:
                self._logger.error(
                    '{key} is not a valid name for a configuration entry. '
                    'Keys must not contain dots as this will interfere with '
                    'configuration access and display.'.format(
                        key=display_key,
                    )
                )
                healthy_schema = False
            if 'description' not in value:
                self._logger.error(
                    '{key} in schema does not have description. '
                    'Please add a description for this schema entry.'.format(
                        key=display_key,
                    )
                )
                healthy_schema = False
        if not healthy_schema:
            raise SchemaError(
                'Schema "{filename}" is not viable. Please correct logged '
                'errors.'.format(filename=schema_file)
            )

        if namespace is None:
            self.schema.update(schema)
        else:
            self.schema[namespace].update(schema)

    def check_config_is_valid(self, namespace=None, fail_on_missing=True):
        schema = self.schema
        config = self._config.copy()
        raw_config = self.raw_config.copy()
        if namespace:
            schema = self.schema[namespace]
            config = config.get(namespace, {}).copy()
            raw_config = raw_config.get(namespace, {}).copy()
        # To allow us to warn on keys that aren't in the schema
        # (e.g. due to typo)
        config.update(raw_config)

        config_valid = True

        for key in config:
            # Determine how to display the key if there are problems
            if namespace is None:
                display_key = key
            else:
                display_key = '.'.join([namespace, key])

            if key in schema:
                if schema[key].get('.is_namespace', False):
                    # Descend into this namespace
                    namespace_valid = self.check_config_is_valid(
                        namespace=key,
                        fail_on_missing=fail_on_missing,
                    )
                    config_valid = config_valid and namespace_valid
                elif fail_on_missing and config.get(key) is NotSet:
                    self._logger.error(
                        '{key} is not set and has no default!'.format(
                            key=display_key,
                        )
                    )
                    config_valid = False
                else:
                    key_value = config.get(key, schema[key].get('default'))
                    valid_values = schema[key].get('valid_values')
                    if valid_values:
                        if key_value not in valid_values:
                            self._logger.error(
                                '{key} is set to "{value}", but this is not '
                                'an allowed value. Allowed values are: '
                                '{allowed}'.format(
                                    key=display_key,
                                    value=key_value,
                                    allowed=', '.join(valid_values),
                                )
                            )
                            config_valid = False

                    validate_dir = schema[key].get('validate_existing_dir')
                    if validate_dir:
                        if not os.path.isdir(key_value):
                            self._logger.error(
                                '{key} is set to "{value}". This key must '
                                'refer to a directory which exists, but the '
                                'specified path is not a directory.'.format(
                                    key=display_key,
                                    value=key_value,
                                )
                            )

                    validate_optional_dir = schema[key].get(
                        'validate_optional_dir')
                    if validate_optional_dir:
                        key_value = None if key_value is NotSet else key_value
                        if key_value and not os.path.isdir(key_value):
                            self._logger.error(
                                '{key} is set to "{value}". If set, this key '
                                'must refer to a directory which exists, but '
                                'the specified path is not a directory.'
                                .format(
                                    key=display_key,
                                    value=key_value,
                                )
                            )
            else:
                self._logger.warn(
                    '{key} is in config, but not defined in the schema. '
                    'This key will not be usable until correctly defined '
                    'in the schema.'.format(key=display_key)
                )
        return config_valid

    @property
    def _config(self):
        if not self._cached_config:
            self._cached_config = self._generate_config()
        return self._cached_config

    def _generate_config(self, schema=None, raw_config=None):
        schema = schema or self.schema
        raw_config = self.raw_config if raw_config is None else raw_config

        # Get all namespaces and config entries at the current level
        namespaces = [
            key for key in schema
            if key != '.is_namespace'
            and schema[key].get('.is_namespace', False)
        ]
        config = {
            k: v.get('default', NotSet)
            for k, v in schema.items()
            if k != '.is_namespace'
        }

        # Populate config values based on user configuration
        for key, value in raw_config.items():
            if key in config:
                config[key] = value

        # Populate namespaces
        for namespace in namespaces:
            config[namespace] = self._generate_config(
                schema=schema[namespace],
                raw_config=raw_config.get(namespace, {}),
            )

        return NameSpace(config, raw_config)

    @property
    def platform(self):
        return self._config[self._config['target_platform']]


def find_schemas():
    schemas = pkg_resources.resource_listdir(
        'cosmo_tester',
        'config_schemas',
    )
    schemas = [
        pkg_resources.resource_filename(
            'cosmo_tester',
            os.path.join('config_schemas', schema),
        )
        for schema in schemas
    ]

    return schemas


def load_config(logger, config_file=None, missing_config_fail=True,
                validate=True):
    """Load the configuration from the specified file.
    missing_config_fail determines whether the file being absent is fatal.
    """
    schemas = find_schemas()
    config = None
    try:
        config = Config(
            config_file=config_file,
            config_schema_files=schemas,
            logger=logger,
        )
    except SchemaError as err:
        raise
    except IOError as err:
        message = 'Could not find config or schema file: {config}'.format(
            config=err.filename,
        )
        if missing_config_fail:
            logger.error(message)
            raise
        else:
            logger.warn(message)

    if validate and not config.check_config_is_valid():
        logger.error(
            'Configuration is invalid, please correct the listed errors.'
        )
        sys.exit(2)
    return config
