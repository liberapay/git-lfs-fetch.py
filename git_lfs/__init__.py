from __future__ import division, print_function, unicode_literals

import json
import os
import pprint
from subprocess import CalledProcessError, check_output, PIPE, Popen, STDOUT
try:
    from urllib.parse import urlsplit, urlunsplit
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import Request, urlopen
    from urllib2 import HTTPError
    from urlparse import urlsplit, urlunsplit

from .utils import force_link, ignore_missing_file, in_dir, TempDir, TempFile


MEDIA_TYPE = 'application/vnd.git-lfs+json'
POST_HEADERS = {'Accept': MEDIA_TYPE, 'Content-Type': MEDIA_TYPE}


def git_show(git_repo, p):
    with in_dir(git_repo):
        return check_output(['git', 'show', 'HEAD:'+p])


def get_cache_dir(git_dir, oid):
    return git_dir+'/lfs/objects/'+oid[:2]+'/'+oid[2:4]


def get_lfs_endpoint_url(git_repo, checkout_dir):
    try:
        with in_dir(checkout_dir):
            url = check_output(
                'git config -f .lfsconfig --get lfs.url'.split()
            ).strip().decode('utf8')
    except CalledProcessError:
        with in_dir(git_repo):
            url = check_output(
                'git config --get remote.origin.url'.split()
            ).strip().decode('utf8')
    if url.endswith('/'):
        url = url[:-1]
    if not url.endswith('/info/lfs'):
        url += '/info/lfs' if url.endswith('.git') else '.git/info/lfs'
    url_split = urlsplit(url)
    host, path = url_split.hostname, url_split.path
    if url_split.scheme != 'https':
        if not url_split.scheme:
            # SSH format: git@example.org:repo.git
            host, path = url_split.path.split('@', 1)[1].split(':', 1)
        url = urlunsplit(('https', host, path, '', ''))
    del url_split

    # need to get GHE auth token if available. issue cmd like this to get:
    # ssh git@git-server.com git-lfs-authenticate foo/bar.git download
    if path.endswith('/info/lfs'):
        path = path[:-len('/info/lfs')]
    auth_header = get_lfs_api_token(host, path)
    return url, auth_header


def get_lfs_api_token(host, path):
    """ gets an authorization token to use to do further introspection on the
        LFS info in the repository.   See documentation here for description of
        the ssh command and response:
        https://github.com/git-lfs/git-lfs/blob/master/docs/api/server-discovery.md
    """
    header_info = {}
    query_cmd = 'ssh git@'+host+' git-lfs-authenticate '+path+' download'
    output = check_output(query_cmd.split()).strip().decode('utf8')
    if output:
        query_resp = json.loads(output)
        header_info = query_resp['header']

    return header_info


def find_lfs_files(checkout_dir):
    """Yields the paths of the files managed by Git LFS
    """
    with in_dir(checkout_dir):
        repo_files = Popen('git ls-files -z'.split(), stdout=PIPE)
        repo_files_attrs = check_output(
            'git check-attr --cached --stdin -z diff filter'.split(),
            stdin=repo_files.stdout
        )
    # In old versions of git, check-attr's `-z` flag only applied to input
    sep = b'\0' if b'\0' in repo_files_attrs else b'\n'
    i = iter(repo_files_attrs.strip(sep).split(sep))
    paths = set()
    while True:
        try:
            if sep == b'\0':
                path, attr, value = next(i), next(i), next(i)
            else:
                path, attr, value = next(i).rsplit(': ', 2)
            attr  # shut up pyflakes
        except StopIteration:
            break
        if value != b'lfs':
            continue
        if path in paths:
            continue
        paths.add(path)
        yield path.decode('ascii')


def read_lfs_metadata(checkout_dir):
    """Yields (path, oid, size) tuples for all files managed by Git LFS
    """
    for path in find_lfs_files(checkout_dir):
        meta = git_show(checkout_dir, path).decode('utf8').strip().split('\n')
        assert meta[0] == 'version https://git-lfs.github.com/spec/v1', meta
        d = dict(line.split(' ', 1) for line in meta[1:])
        oid = d['oid']
        oid = oid[7:] if oid.startswith('sha256:') else oid
        size = int(d['size'])
        yield (path, oid, size)


def fetch_urls(lfs_url, lfs_auth_info, oid_list):
    """Fetch the URLs of the files from the Git LFS endpoint
    """
    objects = []
    data = json.dumps({'operation': 'download', 'objects': oid_list})
    headers = dict(POST_HEADERS)
    headers.update(lfs_auth_info)
    req = Request(lfs_url+'/objects/batch', data.encode('ascii'), headers)

    try:
        resp = json.loads(urlopen(req).read().decode('ascii'))
        assert 'objects' in resp, resp
        objects.extend(resp['objects'])

    except HTTPError as err:
        if err.code != 413:
            raise

        # It is possible for remote server to respond with 413 Request Entity
        # Too Large. If that happens try to request for two sets of oids so
        # request is smaller.
        objects.extend(
            fetch_urls(lfs_url, lfs_auth_info, oid_list[:len(oid_list) // 2])
        )
        objects.extend(
            fetch_urls(lfs_url, lfs_auth_info, oid_list[len(oid_list) // 2:])
        )

    return objects


def fetch(git_repo, checkout_dir=None, verbose=0):
    """Download all the files managed by Git LFS
    """
    git_dir = git_repo+'/.git' if os.path.isdir(git_repo+'/.git') else git_repo
    checkout_dir = checkout_dir or git_repo
    if checkout_dir == git_dir:
        print('Can\'t checkout into a bare repo, please provide a valid '
              'checkout_dir')
        raise SystemExit(1)
    checkout_git_dir = checkout_dir+'/.git'
    if not os.path.isdir(checkout_git_dir):
        with TempDir(dir=checkout_dir) as d:
            check_output(['git', 'clone', '-ns', git_repo, d], stderr=STDOUT)
            os.rename(d+'/.git', checkout_git_dir)
            with in_dir(checkout_dir):
                check_output(['git', 'reset', 'HEAD'])

    # Read the LFS metadata
    found = False
    oid_list, lfs_files = [], {}
    for path, oid, size in read_lfs_metadata(checkout_dir):
        found = True
        dst = checkout_dir+'/'+path

        # Skip the file if it looks like it's already there
        with ignore_missing_file():
            if os.stat(dst).st_size == size:
                if verbose > 1:
                    print('Skipping', path, '(already present)')
                continue

        # If we have the file in the cache, link to it
        with ignore_missing_file():
            cached = get_cache_dir(git_dir, oid)+'/'+oid
            if os.stat(cached).st_size == size:
                force_link(cached, dst)
                if verbose > 0:
                    print('Linked', path, 'from the cache')
                continue

        oid_list.append(dict(oid=oid, size=size))
        lfs_files[(oid, size)] = path

    if not found:
        print('This repository does not seem to use LFS.')
        return

    if not oid_list:
        if verbose > 0:
            print('Nothing to fetch.')
        return

    # Fetch the URLs of the files from the Git LFS endpoint
    lfs_url, lfs_auth_info = get_lfs_endpoint_url(git_repo, checkout_dir)

    if verbose > 0:
        print('Fetching URLs from %s ...' % lfs_url)
    if verbose > 1:
        print('Authorization info for URL: %s' % lfs_auth_info)
        print('oid_list: %s' % pprint.pformat(oid_list))
    objects = fetch_urls(lfs_url, lfs_auth_info, oid_list)

    # Download the files
    tmp_dir = git_dir+'/lfs/tmp'
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    for obj in objects:
        oid, size = (obj['oid'], obj['size'])
        path = lfs_files[(oid, size)]
        cache_dir = get_cache_dir(git_dir, oid)

        # Download into tmp_dir
        with TempFile(dir=tmp_dir) as f:
            url = obj['actions']['download']['href']
            head = obj['actions']['download']['header']
            print('Downloading %s (%s bytes) from %s...' %
                  (path, size, url if verbose > 0 else url[:40]))
            h = urlopen(Request(url, headers=head))
            while True:
                buf = h.read(10240)
                if not buf:
                    break
                f.write(buf)

            # Move to cache_dir
            dst1 = cache_dir+'/'+oid
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            if verbose > 1:
                print('temp download file: ' + f.name)
                print('cache file name: ' + dst1)
            os.rename(f.name, dst1)

        # Copy into checkout_dir
        dst2 = checkout_dir+'/'+path
        force_link(dst1, dst2)
