import unittest
import string
from random import randint

from gevent_fastcgi.base import *
from gevent_fastcgi.utils import pack_pairs, unpack_pairs, BufferedReader, PartialRead
from gevent_fastcgi.test.utils import MockSocket


class PackingTests(unittest.TestCase):

    def test_pack_unpack(self):
        pairs = [
                (string.ascii_lowercase, string.printable),
                (string.ascii_letters, string.punctuation),
                ]
        self.assertEqual(pairs, list(unpack_pairs(pack_pairs(pairs))))

        # check if it works for names/values longer than 127 bytes
        pairs = [(name * 137, value * 731) for name, value in pairs]
        self.assertEqual(pairs, list(unpack_pairs(pack_pairs(pairs))))

        # check if it works for dict too
        pairs = dict(pairs)
        self.assertEqual(pairs, dict(unpack_pairs(pack_pairs(pairs))))


class BufferedReaderTests(unittest.TestCase):

    def test_read_bytes(self):
        
        def get_next_chunk(size):
            return 's' * randint(1, size)

        reader = BufferedReader(get_next_chunk, 16)

        self.assertEqual('s' * 77, reader.read_bytes(77))

    def test_partial_read(self):
        sock = MockSocket('12345') # less than 8 bytes (record header size)
        conn = Connection(sock)
        with self.assertRaises(PartialRead):
            conn.read_record()

