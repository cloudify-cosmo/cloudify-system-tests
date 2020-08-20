import argparse
import subprocess

import yaml


def generate_replace_certs_config(replace_certs_config_path, host_ip):
    subprocess.call(['cfy', 'certificates', 'generate-replace-config', '-o',
                     '{0}'.format(replace_certs_config_path)])
    with open(replace_certs_config_path) as replace_certs_file:
        replace_certs_config = yaml.load(replace_certs_file, yaml.Loader)

    certs_dir = '~/.cloudify-test-ca/'
    ca_path = certs_dir + 'ca.crt'
    for instance_name, instance_dict in replace_certs_config.items():
        cert_path = certs_dir + host_ip + '.crt'
        key_path = certs_dir + host_ip + '.key'
        for cert_name in instance_dict:
            if 'ca' in cert_name:
                instance_dict[cert_name] = ca_path
            elif 'cert' in cert_name:
                instance_dict[cert_name] = cert_path
            elif 'key' in cert_name:
                instance_dict[cert_name] = key_path

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
    parser.add_argument(
        '--host-ip',
        help='The IP of this manager',
        required=True,
    )

    args = parser.parse_args()
    generate_replace_certs_config(args.output, args.host_ip)


if __name__ == '__main__':
    main()
