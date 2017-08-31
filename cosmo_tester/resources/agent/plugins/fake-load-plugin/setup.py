
from setuptools import setup


version = "4.1"


install_requires = [
    "cloudify-agent=={version}",
    "cloudify-plugins-common=={version}",
    "flask",
    "kombu",
    "librabbitmq",
    "requests",
    ]

install_requires = [s.format(version=version) for s in install_requires]


setup(
    name="cloudify-fake-agent-plugin",
    packages=["cloudify_fake_load"],
    version=version,
    install_requires=install_requires,
    )
