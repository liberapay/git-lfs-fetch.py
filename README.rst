A lightweight Git Large File Storage fetcher written in python.

This module cannot fully replace the official git-lfs client, it only knows how
to download the files, cache them (the same way the official client does), and
place them in a checkout directory. Uploading files is not implemented at all.

Installation
============

    pip install git-lfs

python-git-lfs is compatible with python 2 and 3.

Usage
=====

Basic: simply run ``python -m git_lfs`` in a normal Git repository.

Advanced::

    python -m git_lfs [-h] [-v] [git_repo] [checkout_dir]

    positional arguments:
    git_repo       if it's bare you need to provide a checkout_dir
    checkout_dir

    optional arguments:
      -h, --help     show this help message and exit
      -v, --verbose

License
=======

`CC0 Public Domain Dedication <http://creativecommons.org/publicdomain/zero/1.0/>`_
