from __future__ import division, print_function, unicode_literals

import argparse

from . import fetch

p = argparse.ArgumentParser()
p.add_argument('git_repo', nargs='?', default='.',
               help="if it's bare you need to provide a checkout_dir")
p.add_argument('checkout_dir', nargs='?')
p.add_argument('-v', '--verbose', action='count', default=0)
args = p.parse_args()

fetch(args.git_repo, args.checkout_dir, args.verbose)
