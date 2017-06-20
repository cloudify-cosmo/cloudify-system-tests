
from setuptools import setup


version = "4.1"


install_requires = [
    "cloudify-plugins-common=={version}",
    "kombu",
    "librabbitmq",
    ]

install_requires = [s.format(version=version) for s in install_requires]


setup(
    name="cloudify-fake-agent-plugin",
    packages=["cloudify_fake_load"],
    version=version,
    install_requires=install_requires,
    )
