from __future__ import division, print_function, unicode_literals

from contextlib import contextmanager
import os
import shutil
from tempfile import mkdtemp, NamedTemporaryFile


@contextmanager
def ignore_missing_file(filename=None):
    try:
        yield
    except OSError as e:
        if e.errno != 2 or filename and e.filename != filename:
            raise


@contextmanager
def in_dir(dirpath):
    # WARNING not thread-safe
    prev = os.path.abspath(os.getcwd())
    os.chdir(dirpath)
    try:
        yield
    finally:
        os.chdir(prev)


@contextmanager
def TempDir(**kw):
    """mkdtemp wrapper that automatically deletes the directory
    """
    d = mkdtemp(**kw)
    try:
        yield d
    finally:
        with ignore_missing_file(d):
            shutil.rmtree(d)


@contextmanager
def TempFile(**kw):
    """NamedTemporaryFile wrapper that doesn't fail if you (re)move the file
    """
    f = NamedTemporaryFile(**kw)
    try:
        yield f
    finally:
        with ignore_missing_file():
            f.__exit__(None, None, None)


def force_link(source, link_name):
    # WARNING not atomic
    with ignore_missing_file():
        os.remove(link_name)
    os.link(source, link_name)
