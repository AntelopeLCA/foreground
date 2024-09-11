from setuptools import setup, find_packages

VERSION = '0.3.3'

requires = [
    'antelope_interface>=0.2.7',
    'antelope_core>=0.3.3'
]

"""
Revision history
0.3.3   2024-09-10 - normalize how directed flows are used in lci()
                     use dependencies() instead of inventory() to extend process models
                     numerous bugfixes to observations and foreground handling

0.3.2   2024-08-15 - move fg methods to interface. lots of remote traversal work

0.3.1   2024-05-15 - "inventory" operations on fragments deprecated
                     tester catalogs now filesystem-free
                     handle unresolved anchor issues 

0.3.0   2024-01-05 - 0.3-branch development version, supporting end-user access to vault.lc resources 

# ^ 0.3.* 0.3-branch fork   
# v 0.2.* main / master for legacy projects

0.2.1 - 21 Jul 2023 - Subfrags comes home-- complete changes throughout the system, impossible to recount.

0.1.7 - 11 Aug 2021 - TRAVIS release

0.1.3 - 30 Dec 2020 - First public release
"""

setup(
    name="antelope_foreground",
    version=VERSION,
    author="Brandon Kuczenski",
    author_email="bkuczenski@ucsb.edu",
    install_requires=requires,
    url="https://github.com/AntelopeLCA/foreground",
    summary="A foreground model building implementation",
    long_description_content_type='text/markdown',
    long_description=open('README.md').read(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: BSD License",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Topic :: Scientific/Engineering"
    ],
    python_requires='>=3.6',
    packages=find_packages()
)
