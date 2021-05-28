import os
import subprocess
import tempfile

from cloudify.decorators import operation


@operation(resumable=True)
def create(ctx):
    """Perform an 'init script' (userdata) based agent install."""
    tempdir = tempfile.mkdtemp(prefix='init_script_test_')
    script_path = os.path.join(tempdir,  'install_script')
    ssh_key_path = os.path.join(tempdir, 'ssh_key')

    with open(ssh_key_path, 'w') as ssh_key_handle:
        ssh_key_handle.write(ctx.node.properties['agent_config']['key'])
    subprocess.check_call(['chmod', '400', ssh_key_path])

    with open(script_path, 'w') as script_handle:
        script_handle.write(ctx.agent.init_script())

    user = ctx.node.properties['agent_config']['user']
    address = '{user}@{ip}'.format(
        user=user,
        ip=ctx.node.properties['ip'])

    subprocess.check_call(['ssh', '-i', ssh_key_path, address,
                           '-o' 'StrictHostKeyChecking=no', 'echo', 'Conn'])
    subprocess.check_call(['scp', '-i', ssh_key_path, script_path,
                           '{}:install_script'.format(address)])
    subprocess.check_call(['ssh', '-i', ssh_key_path, address, 'chmod', '+x',
                           './install_script'])
    subprocess.check_call(['ssh', '-i', ssh_key_path, address,
                           'sudo', './install_script'])
