from setuptools import setup, find_packages

requires = [
    'antelope_core>=0.1.7'
]

"""
Revision history

0.1.7 - 11 Aug 2021 - TRAVIS release

0.1.3 - 30 Dec 2020 - First public release
"""

setup(
    name="antelope_foreground",
    version="0.1.7",
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
