#!/usr/bin/env python
import sys
from setuptools import setup
from setuptools.command.install import install


class Installer(install):
    pass


with open('README.md', 'r') as f:
    long_description = f.read()

setup(name='corintick',
      version='0.1.0',
      description='Column-based datastore for historical timeseries streamers',
      long_description=long_description,
      author='Gustavo Bezerra',
      author_email='gusutabopb@gmail.com',
      url='https://github.com/plugaai/corintick',
      packages=['corintick'],
      python_requires='>=3.6',
      license='GPL',
      install_requires=['lz4>=0.9.4',
                        'pandas>=0.19', 'pandas-datareader',
                        'pymongo', 'numpy', 'quandl', 'msgpack-python'],
      classifiers=[
          'Intended Audience :: Developers',
          'Intended Audience :: Science/Research',
          'Intended Audience :: Financial and Insurance Industry',
          'Development Status :: 3 - Alpha',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6'
          "Topic :: Database",
          "Topic :: Database :: Front-Ends",
          "Topic :: Software Development :: Libraries",
      ])
