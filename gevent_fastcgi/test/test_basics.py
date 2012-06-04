import unittest
import string

from gevent_fastcgi.base import pack_pairs, unpack_pairs, InputStream


class TestBasics(unittest.TestCase):

    def test_pack_unpack(self):
        pairs = [
                (string.ascii_lowercase, string.printable),
                (string.ascii_letters, string.punctuation),
                ]
        self.assertEqual(pairs, list(unpack_pairs(pack_pairs(pairs))))

        # check if it still works for names/values longer than 127 bytes
        pairs = [(name * 137, value * 731) for name, value in pairs]
        self.assertEqual(pairs, list(unpack_pairs(pack_pairs(pairs))))

        # check if it works for dict too
        pairs = dict(pairs)
        self.assertEqual(pairs, dict(unpack_pairs(pack_pairs(pairs))))

    def test_input_stream_short(self):
        # data length is less than stream's max_mem (landing point)
        data = string.ascii_letters
        stream = InputStream(1024)

        stream.feed(data)
        self.assertFalse(stream.landed)

        stream.feed('') # EOF
        self.assertFalse(stream.landed)
        self.assertEqual(data, stream.read())

    def test_input_stream_long(self):
        # data length is greater than stream's max_mem (landing point)
        max_mem = 1024
        data = string.ascii_letters * max_mem
        stream = InputStream(max_mem)

        stream.feed(data)
        self.assertTrue(stream.landed)

        stream.feed('') # EOF
        self.assertTrue(stream.landed)
        self.assertEqual(data, stream.read())
