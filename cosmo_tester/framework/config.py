import pkg_resources
import warnings
import yaml

import os
import sys


class SchemaError(Exception):
    pass


class NotSet(object):
    def __repr__(self):
        return 'not set'


class Config(object):
    schema = {}
    raw_config = {}
    namespaces = set([None])
    _config = None

    def __init__(self, config_file, config_schema_files, logger):
        self.logger = logger

        # Load all initially supplied schemas
        for schema in config_schema_files:
            self.update_schema(schema)
        # We'll be pretty useless if we allow no config
        if len(self.schema) == 0:
            raise SchemaError('No valid config entries loaded from schemas.')

        # Load config
        if config_file:
            self.update_config(config_file)

    def _nest_dotted_key(self, root_dict, key_path, value):
        this_key = key_path.pop(0)

        if len(key_path) == 0:
            root_dict[this_key] = value
        else:
            if this_key not in root_dict.keys():
                root_dict[this_key] = {}
            self._nest_dotted_key(
                root_dict[this_key],
                key_path=key_path,
                value=value,
            )

    def update_config(self, config_file):
        with open(config_file) as config_handle:
            raw_config = yaml.load(config_handle.read())
        processed_config = {}
        for key in raw_config.keys():
            key_path = key.split('.')
            self._nest_dotted_key(
                processed_config,
                key_path,
                raw_config.pop(key),
            )
        self.raw_config.update(processed_config)
        self.check_config_is_valid()

    def update_schema(self, schema_file):
        with open(schema_file) as schema_handle:
            schema = yaml.load(schema_handle.read())

        namespace = None
        if 'namespace' in schema.keys():
            namespace = schema['namespace']
            self.namespaces.add(namespace)
            if namespace in self.schema.keys():
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
                self.logger.error(
                    '{key} is not a valid name for a configuration entry. '
                    'Keys must not contain dots as this will interfere with '
                    'configuration access and display.'.format(
                        key=display_key,
                    )
                )
                healthy_schema = False
            if 'description' not in value.keys():
                self.logger.error(
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
        self.check_config_is_valid()

    def check_config_is_valid(self, namespace=None):
        # Allow the existence of, but warn about, config keys that aren't in
        # the schema.
        # They will not be usable.
        if namespace is None:
            schema = self.schema
            config = self.raw_config
        else:
            schema = self.schema[namespace]
            config = self.raw_config.get(namespace, {})
        for key in config.keys():
            if namespace is None:
                display_key = key
            else:
                display_key = '.'.join([namespace, key])
            if key not in schema.keys():
                self.logger.warn(
                    '{key} is in config, but not defined in the schema. '
                    'This key will not be usable until correctly defined '
                    'in the schema.'.format(key=display_key)
                )
            if key in schema.keys() and schema[key].get('.is_namespace',
                                                        False):
                self.check_config_is_valid(namespace=key)
        # Currently, if we can load it then it's valid.
        return True

    def _generate_config(self, schema=None, raw_config=None):
        schema = schema or self.schema
        raw_config = raw_config or self.raw_config

        # Get all namespaces and config entries at the current level
        namespaces = [
            key for key in schema.keys()
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

        return config

    def __getitem__(self, item):
        if not self._config:
            self._config = self._generate_config()
        config = self._config

        if item in config.keys():
            return config[item]
        else:
            if item in self.raw_config.keys():
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

    def keys(self):
        return self._generate_config().keys()

    def values(self):
        return self._generate_config().values()

    def items(self):
        return self._generate_config().items()


def find_schemas():
    # I'm not entirely keen on ignoring the userwarning here,
    # but it seems like both Ubuntu and centos default to group
    # writeable ~/.python-eggs, which triggers this warning.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', category=UserWarning)
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


def load_config(logger, config_file=None, missing_config_fail=True):
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
        print(str(err))
        sys.exit(1)
    except IOError as err:
        message = 'Could not find config or schema file: {config}'.format(
            config=err.filename,
        )
        if missing_config_fail:
            logger.error(message)
            sys.exit(2)
        else:
            logger.warn(message)
    return config


def validate_config(config, logger):
    """Validate the configuration against the schema."""
    valid = True
    namespaces = config.namespaces
    not_set_message = '{key} is not set and has no default!'
    for namespace in namespaces:
        if namespace is None:
            check = config.items()
        else:
            check = config[namespace].items()
        for key, value in check:
            display_key = key
            if namespace is not None:
                display_key = '.'.join([namespace, key])
            if key not in namespaces:
                if value is NotSet:
                    logger.error(not_set_message.format(
                        key=display_key,
                    ))
                    valid = False
    return valid
