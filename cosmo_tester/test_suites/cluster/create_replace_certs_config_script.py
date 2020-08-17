import argparse
import subprocess

import yaml


def generate_replace_certs_config(replace_certs_config_path):
    subprocess.call(['cfy', 'certificates', 'generate-replace-config', '-o',
                     '{0}'.format(replace_certs_config_path)])
    with open(replace_certs_config_path) as replace_certs_file:
        replace_certs_config = yaml.load(replace_certs_file, yaml.Loader)

    certs_dir = '~/.cloudify-test-ca/'
    ca_path = certs_dir + 'ca.crt'
    for instance_name in 'manager', 'postgresql_server', 'rabbitmq':
        for node in replace_certs_config[instance_name]['cluster_members']:
            cert_path = certs_dir + node['host_ip'] + '.crt'
            key_path = certs_dir + node['host_ip'] + '.key'
            for cert_name in node:
                if 'ca' in cert_name:
                    node[cert_name] = ca_path
                elif 'cert' in cert_name:
                    node[cert_name] = cert_path
                elif 'key' in cert_name:
                    node[cert_name] = key_path
        for key in replace_certs_config[instance_name]:
            if 'ca' in key:
                replace_certs_config[instance_name][key] = ca_path

    with open(replace_certs_config_path, 'w') as certs_file:
        yaml.dump(replace_certs_config, certs_file)


def main():
    parser = argparse.ArgumentParser(
        description='Create the replace certificates config file'
    )
    parser.add_argument(
        '--output',
        help='Path of the replace certificates config file',
        required=True,
    )

    args = parser.parse_args()
    generate_replace_certs_config(args.output)


if __name__ == '__main__':
    main()
