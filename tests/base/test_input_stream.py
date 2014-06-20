from __future__ import absolute_import, with_statement

import unittest

from gevent import Timeout

from gevent_fastcgi.base import Connection, InputStream
from ..utils import binary_data, text_data, MockSocket


class InputStreamTests(unittest.TestCase):

    def setUp(self):
        self.sock = MockSocket()
        self.conn = Connection(self.sock)
        self.stream = InputStream(self.conn)

    def tearDown(self):
        del self.stream
        del self.conn
        del self.sock

    def test_feed_stream(self):
        stream = self.stream

        data_in = binary_data()
        stream.feed(data_in)
        stream.feed('')

        self.assertRaises(IOError, stream.feed, binary_data(1))
        self.assertRaises(IOError, stream.feed, '')

        data = stream.read()
        assert data == data_in

    def test_iter(self):
        stream = self.stream
        data_in = [text_data() + '\r\n' for _ in xrange(17)]

        map(stream.feed, data_in)
        stream.feed('')

        for line_in, line_out in zip(data_in, stream):
            assert line_in == line_out

    def test_blocks_until_eof(self):
        stream = self.stream
        data = binary_data()
        stream.feed(data)

        # no EOF mark was fed
        with self.assertRaises(Timeout):
            with Timeout(2):
                stream.read()

    def test_readlines(self):
        stream = self.stream
        data_in = [text_data() + '\r\n' for _ in xrange(13)]
        map(stream.feed, data_in)
        stream.feed('')

        data_out = stream.readlines()
        assert data_out == data_in, data_out
