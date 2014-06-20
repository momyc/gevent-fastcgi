from __future__ import absolute_import, with_statement

import unittest
from random import randint

from gevent import sleep, Timeout

from gevent_fastcgi.const import (
    FCGI_STDOUT,
    FCGI_STDERR,
    FCGI_MAX_CONTENT_LEN,
)

from gevent_fastcgi.base import Connection, StdoutStream, StderrStream
from ..utils import binary_data, text_data, MockSocket


class StreamTestsBase(object):

    def setUp(self):
        self.sock = MockSocket()
        self.conn = Connection(self.sock)

    def tearDown(self):
        del self.conn
        del self.sock

    def stream(self, conn=None, request_id=None):
        if conn is None:
            conn = self.conn
        if request_id is None:
            request_id = randint(1, 65535)
        return self.stream_class(conn, request_id)

    def test_constructor(self):
        conn = self.conn

        self.assertRaises(TypeError, self.stream_class)
        self.assertRaises(TypeError, self.stream_class, conn)

        stream = self.stream_class(conn, 333)
        assert stream.conn is conn
        assert stream.request_id == 333
        assert stream.record_type == self.stream_class.record_type
        assert not stream.closed

    def test_write(self):
        stream = self.stream()
        data = [binary_data(1024, 1) for _ in range(13)]

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

        received = []
        for record in self.conn:
            assert record.type == stream.record_type
            assert record.request_id == stream.request_id
            received.append(record.content)
        assert ''.join(received) == ''.join(data)

    def test_long_writelines(self):
        stream = self.stream()

        data = [binary_data(37137) for _ in range(3)]
        stream.writelines(data)

        self.sock.flip()

        received = []
        for record in self.conn:
            assert record.type == stream.record_type
            assert record.request_id == stream.request_id
            received.append(record.content)
        assert ''.join(received) == ''.join(data)

    def test_empty_write(self):
        conn = self.conn
        # calling this would raise AttributeError
        conn.write_record = None

        stream = self.stream(conn=conn)
        stream.write('')
        stream.flush()
        stream.writelines('' for _ in range(13))

    def test_close(self):
        stream = self.stream()

        # should send EOF record
        stream.close()
        # should fail since stream was closed
        self.assertRaises(IOError, stream.write, '')
        self.assertRaises(IOError, stream.writelines, (text_data(137)
                                                       for _ in range(3)))

        self.sock.flip()

        # should receive EOF record
        record = self.conn.read_record()
        assert record.type == stream.record_type
        assert record.content == ''
        assert record.request_id == stream.request_id

        assert self.conn.read_record() is None


class StdoutStreamTests(StreamTestsBase, unittest.TestCase):

    stream_class = StdoutStream

    def test_writelines(self):
        stream = self.stream()

        def app_iter(delay):
            yield text_data(137)
            sleep(delay)
            yield text_data(137137)

        with self.assertRaises(Timeout):
            Timeout(1).start()
            stream.writelines(app_iter(3))


class StderrStreamTests(StreamTestsBase, unittest.TestCase):

    stream_class = StderrStream

    def test_writelines(self):
        stream = self.stream()
        data = [text_data(7) + '\r\n' for _ in xrange(3)]

        stream.writelines(data)

        self.sock.flip()

        data_in = ''.join(data)
        data_out = ''.join(record.content for record in self.conn
                           if (record.type == stream.record_type
                               and record.request_id == stream.request_id))

        assert data_in == data_out
