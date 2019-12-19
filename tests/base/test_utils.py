from __future__ import absolute_import

import sys
import imp
import unittest
from itertools import product

from gevent_fastcgi.utils import pack_pairs, unpack_pairs


SHORT_STR = b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
MEDIUM_STR = SHORT_STR * 32
LONG_STR = MEDIUM_STR * 32
STRINGS = (b'', SHORT_STR, MEDIUM_STR, LONG_STR)


class UtilsTests(unittest.TestCase):

    def test_pack_unpack_pairs(self):
        pairs = tuple(product(STRINGS, STRINGS))

        assert pairs == tuple(unpack_pairs(pack_pairs(pairs)))

    def test_too_long(self):
        TOO_LONG_STR = LONG_STR * int(0x7fffffff / len(LONG_STR) + 1)
        pairs = product(STRINGS, (TOO_LONG_STR,))

        for pair in pairs:
            with self.assertRaises(ValueError):
                pack_pairs((pair,))


class NoSpeedupsUtilsTests(UtilsTests):
    """
    Makes importing gevent_fastcgi.speedups fail with ImportError to enforce
    usage of Python implementation of pack_pairs/unpack_pairs
    """
    def setUp(self):
        sys.modules['gevent_fastcgi.speedups'] = None
        if 'gevent_fastcgi.utils' in sys.modules:
            sys.modules['gevent_fastcgi.utils'] = imp.reload(
                sys.modules['gevent_fastcgi.utils'])

    def tearDown(self):
        del sys.modules['gevent_fastcgi.speedups']
        sys.modules['gevent_fastcgi.utils'] = imp.reload(
            sys.modules['gevent_fastcgi.utils'])


if __name__ == '__main__':
    unittest.main()
