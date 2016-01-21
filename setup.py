from os.path import join, dirname

from setuptools import setup, find_packages

from version import get_version

setup(
    name='git-lfs',
    version=get_version(),
    description='A lightweight Git Large File Storage fetcher',
    author='Changaco',
    author_email='changaco@changaco.oy.lc',
    url='https://github.com/liberapay/git-lfs-fetch.py',
    license='CC0',
    packages=find_packages(exclude=['tests']),
    long_description=open(join(dirname(__file__), 'README.rst')).read(),
    keywords='git lfs',
)
