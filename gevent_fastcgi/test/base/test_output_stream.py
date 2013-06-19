from __future__ import absolute_import, with_statement

import unittest
from random import randint

from ...const import (
    FCGI_STDOUT,
    FCGI_STDERR,
    FCGI_MAX_CONTENT_LEN,
)

from ...base import Connection, OutputStream
from ..utils import binary_data, text_data, MockSocket


class OutputStreamTest(unittest.TestCase):

    def setUp(self):
        self.sock = MockSocket()
        self.conn = Connection(self.sock)

    def tearDown(self):
        del self.conn
        del self.sock

    def stream(self, record_type=FCGI_STDOUT):
        return OutputStream(self.conn, randint(1, 65535), record_type)

    def test_constructor(self):
        conn = self.conn

        self.assertRaises(TypeError, OutputStream)
        self.assertRaises(TypeError, OutputStream, conn)
        self.assertRaises(TypeError, OutputStream, conn, 222)
        self.assertRaises(ValueError, OutputStream, conn, 111, 222)

        for stream_type in FCGI_STDOUT, FCGI_STDERR:
            stream = OutputStream(conn, 333, stream_type)
            assert stream.conn is conn
            assert stream.request_id == 333
            assert stream.record_type == stream_type
            assert not stream.closed

    def test_write(self):
        stream = self.stream(FCGI_STDERR)
        data = [binary_data(1, 1024) for _ in range(13)]

        map(stream.write, data)

        self.sock.flip()

        for chunk, record in zip(data, self.conn):
            assert record.type == stream.record_type
            assert record.request_id == stream.request_id
            assert record.content == chunk
        assert self.conn.read_record() is None

    def test_long_write(self):
        stream = self.stream()

        data = binary_data(FCGI_MAX_CONTENT_LEN * 3 + 13713)
        stream.write(data)

        self.sock.flip()

        sent = 0
        for record in self.conn:
            assert record.type == stream.record_type
            assert record.request_id == stream.request_id
            sent += len(record.content)
        assert sent == len(data)

    def test_empty_write(self):
        stream = self.stream()

        stream.write('')
        stream.flush()
        # should not send any record
        assert self.sock.output == ''

    def test_close(self):
        stream = self.stream()

        # should send EOF record
        stream.close()
        # should fail since stream was closed
        self.assertRaises(IOError, stream.write, '')

        self.sock.flip()

        # should receive EOF record
        record = self.conn.read_record()
        assert record.type == stream.record_type
        assert record.content == ''
        assert record.request_id == stream.request_id

        assert self.conn.read_record() is None

    def test_writelines(self):
        stream = self.stream()
        data = [text_data(7) + '\r\n' for _ in xrange(3)]

        stream.writelines(data)

        self.sock.flip()

        data_in = ''.join(data)
        data_out = ''.join(record.content for record in self.conn
                           if (record.type == stream.record_type
                               and record.request_id == stream.request_id))

        assert data_in == data_out, '{0!r} != {1!r}'.format(data_in, data_out)
