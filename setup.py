#!/usr/bin/env python
# -*- coding: utf-8 -*-

try:
    import setuptools
except ImportError:
    import distutils.core as setuptools


__author__ = 'Peter Bryzgalov'
__copyright__ = 'Copyright 2015'
__credits__ = []

__license__ = 'Apache 2.0'
__version__ = '0.8.15d'
__maintainer__ = __author__
__email__ = 'peterbryz@yahoo.com'
__status__ = 'Beta'

__title__ = 'docker-registry-driver-git'
__build__ = 0x000001

__url__ = 'https://github.com/pyotr777/docker-registry-driver-git'
__description__ = 'Docker registry backend git driver'
d = ''

setuptools.setup(
    name=__title__,
    version=__version__,
    author=__author__,
    author_email=__email__,
    maintainer=__maintainer__,
    maintainer_email=__email__,
    url=__url__,
    description=__description__,
    download_url=d,
    long_description=open('./README.md').read(),
    classifiers=['Development Status :: 4 - Beta',
                 'Intended Audience :: Developers',
                 'Programming Language :: Python',
                 'Programming Language :: Python :: 2.7',
                 'Operating System :: OS Independent',
                 'Topic :: Utilities',
                 'License :: OSI Approved :: Apache Software License'],
    platforms=['Independent'],
    license=open('./LICENSE').read(),
    namespace_packages=['docker_registry', 'docker_registry.drivers'],
    packages=['docker_registry', 'docker_registry.drivers'],
    install_requires=open('./requirements.txt').read(),
    zip_safe=True,
    test_suite='nose.collector'
)
