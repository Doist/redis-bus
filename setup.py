# -*- coding: utf-8 -*-
import os
from setuptools import setup

def read(fname):
    try:
        return open(os.path.join(os.path.dirname(__file__), fname)).read()
    except:
        return ''

setup(
    name='redis-bus',
    version='0.1',
    py_modules=['redis_bus'],
    author='Roman Imankulov',
    author_email='roman.imankulov@gmail.com',
    license='BSD',
    url='https://github.com/doist/redis-bus',
    description='Redis Bus implementation',
    long_description = read('README.rst'),
    install_requires = ['redis', 'werkzeug'],
    # see here for complete list of classifiers
    # http://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=(
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
    ),
    entry_points={
        'console_scripts': [
            'redis-bus = redis_bus:main',
        ]
    }
)
