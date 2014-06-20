from __future__ import absolute_import

import sys
import unittest
from itertools import product

from gevent_fastcgi.utils import pack_pairs, unpack_pairs


SHORT_STR = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
LONG_STR = SHORT_STR * 32
STRINGS = ('', SHORT_STR, LONG_STR)


class UtilsTests(unittest.TestCase):

    def test_pack_unpack_pairs(self):
        pairs = tuple(product(STRINGS, STRINGS))

        assert pairs == tuple(unpack_pairs(pack_pairs(pairs)))


class NoSpeedupsUtilsTests(UtilsTests):
    """
    Makes importing gevent_fastcgi.speedups fail with ImportError to enforce
    usage of Python implementation of pack_pairs/unpack_pairs
    """
    def setUp(self):
        sys.modules['gevent_fastcgi.speedups'] = None
        if 'gevent_fastcgi.utils' in sys.modules:
            sys.modules['gevent_fastcgi.utils'] = reload(
                sys.modules['gevent_fastcgi.utils'])

    def tearDown(self):
        del sys.modules['gevent_fastcgi.speedups']
        sys.modules['gevent_fastcgi.utils'] = reload(
            sys.modules['gevent_fastcgi.utils'])


if __name__ == '__main__':
    unittest.main()
