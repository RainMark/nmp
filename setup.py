#!/bin/env python3

from setuptools import find_packages, setup

setup(
    name='nmp',
    version='0.2.0',
    author='RainMark',
    author_email='rain.by.zhou@gmail.com',
    description='Network Multistage Pxxxx/Net Manager Project',
    url='https://github.com/RainMark/nmp',
    classifiers=[
        'Operating System :: Microsoft :: Windows',
        'Operating System :: Unix',
        'Operating System :: MacOS',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3 :: Only',
        'License :: OSI Approved :: MIT License',
    ],

    packages=find_packages(),
    python_requires='>=3.8',
    include_package_data=True,
    zip_safe=True,
    install_requires = [
        'certifi >= 2024.7.4',
        'websockets >= 12.0, < 14.0',
        'coloredlogs == 15.0.1',
        'tomli >= 2.0.1; python_version < "3.11"',
    ],
    extras_require={
        'desktop': [
            'PySide6-Essentials == 6.11.2',
        ],
    },

    entry_points={
        'console_scripts':[
            'nmp = nmp.main:main',
        ]
    },
)
