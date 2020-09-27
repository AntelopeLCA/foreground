from setuptools import setup

requires = [
#    'antelope_catalog',
#    'lcatools'
]

setup(
    name="antelope_foreground",
    version="0.0.3",
    author="Brandon Kuczenski",
    author_email="bkuczenski@ucsb.edu",
    install_requires=requires,
    url="https://github.com/AntelopeLCA/foreground",
    summary="A foreground model building implementation",
    long_description=open('README.md').read(),
    packages=['antelope_foreground']
)
