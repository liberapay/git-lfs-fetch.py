#!/usr/bin/env python

from __future__ import division, print_function, unicode_literals

import argparse
from contextlib import contextmanager
import json
import os
from subprocess import check_output, PIPE, Popen
from tempfile import NamedTemporaryFile
try:
    from urllib.parse import urlsplit, urlunsplit
    from urllib.request import Request, urlopen
except ImportError:
    from urllib2 import Request, urlopen
    from urlparse import urlsplit, urlunsplit

MEDIA_TYPE = 'application/vnd.git-lfs+json'

@contextmanager
def ignore_missing_file():
    try:
        yield
    except OSError as e:
        if e.errno != 2:
            raise

@contextmanager
def TempFile(**kw):
    f = NamedTemporaryFile(**kw)
    try:
        yield f
    finally:
        with ignore_missing_file():
            f.__exit__(None, None, None)

def force_link(source, link_name):
    with ignore_missing_file():
        os.remove(link_name)
    os.link(source, link_name)

git_show = lambda p: check_output(['git', 'show', 'HEAD:'+p]).decode('utf8')

# Parse command line arguments
p = argparse.ArgumentParser()
p.add_argument('git_repo', nargs='?', default='.')
p.add_argument('checkout_dir', nargs='?', help='default is based on the value of the previous argument')
args = p.parse_args()
args.checkout_dir = args.checkout_dir or args.git_repo
git_dir = args.git_repo
git_dir = git_dir+'/.git' if os.path.isdir(git_dir+'/.git') else git_dir
get_cache_dir = lambda oid: git_dir+'/lfs/objects/'+oid[:2]+'/'+oid[2:4]

# Build the Git LFS endpoint URL
os.chdir(args.git_repo)
origin_url = check_output('git config --get remote.origin.url'.split()).strip().decode('utf8')
lfs_url = origin_url
if not origin_url.startswith('https://'):
    url = urlsplit(origin_url)
    if url.scheme:
        lfs_url = urlunsplit('https', url.hostname, url.path, url.query)
    else:
        # SSH format: git@example.org:repo.git
        lfs_url = 'https://'+'/'.join(origin_url.split('@', 1)[1].split(':', 1))
lfs_url = lfs_url+'/info/lfs'

# Find the files managed by Git LFS
repo_files = Popen('git ls-files -z'.split(), stdout=PIPE)
repo_files_attrs = check_output('git check-attr -z --stdin diff'.split(),
                                stdin=repo_files.stdout)
i = iter(repo_files_attrs.split(b'\0'))
data, paths, lfs_files = [], set(), {}
while True:
    try:
        path, attr, value = next(i).decode('utf8'), next(i), next(i)
    except StopIteration:
        break
    if value != b'lfs':
        continue
    if path in paths:
        continue
    paths.add(path)

    # Read the LFS metadata
    meta = git_show(path).strip().split('\n')
    assert meta[0] == 'version https://git-lfs.github.com/spec/v1', meta
    d = dict(line.split(' ', 1) for line in meta[1:])
    oid = d['oid']
    oid = oid[7:] if oid.startswith('sha256:') else oid
    size = int(d['size'])
    dst = args.checkout_dir+'/'+path

    # Skip the file if it looks like it's already there
    with ignore_missing_file():
        if os.stat(dst).st_size == size:
            continue

    # If we have the file in the cache, link to it
    with ignore_missing_file():
        cached = get_cache_dir(oid)
        if os.stat(cached).st_size == size:
            force_link(cached, dst)
            continue

    data.append(dict(oid=oid, size=size))
    lfs_files[(oid, size)] = path

if not data:
    raise SystemExit(0)

# Fetch the URLs of the files from the Git LFS endpoint
data = json.dumps({'operation': 'download', 'objects': data}).encode('utf8')
headers = {'Accept': MEDIA_TYPE, 'Content-Type': MEDIA_TYPE}
req = Request(lfs_url+'/objects/batch', data, headers)
resp = json.loads(urlopen(req).read().decode('ascii'))
assert len(resp.get('objects', '')) == len(lfs_files), resp

# Download the files
tmp_dir = git_dir+'/lfs/tmp'
if not os.path.exists(tmp_dir):
    os.makedirs(tmp_dir)
for obj in resp['objects']:
    oid, size = (obj['oid'], obj['size'])
    path = lfs_files[(oid, size)]
    cache_dir = get_cache_dir(oid)

    # Download into tmp_dir
    with TempFile(dir=tmp_dir) as f:
        url = obj['actions']['download']['href']
        print('Downloading %s (%s bytes) from %s...' % (path, size, url[:40]))
        h = urlopen(Request(url))
        while True:
            buf = h.read(10240)
            if not buf:
                break
            f.write(buf)

        # Move to cache_dir
        dst1 = cache_dir+'/'+oid
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        os.rename(f.name, dst1)

    # Copy into checkout_dir
    dst2 = args.checkout_dir+'/'+path
    force_link(dst1, dst2)
