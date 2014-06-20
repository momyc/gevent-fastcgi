from __future__ import absolute_import, with_statement

import unittest
from random import randint

from gevent_fastcgi.const import (
    FCGI_STDIN,
    FCGI_STDOUT,
    FCGI_STDERR,
    FCGI_DATA,
    FCGI_RECORD_TYPES,
    FCGI_RECORD_HEADER_LEN,
    FCGI_MAX_CONTENT_LEN,
)
from gevent_fastcgi.base import Record, Connection, PartialRead
from ..utils import binary_data, MockSocket


class ConnectionTests(unittest.TestCase):

    def setUp(self):
        self.sock = MockSocket()

    def tearDown(self):
        del self.sock

    def test_read_write(self):
        record_type = FCGI_DATA
        request_id = randint(1, 65535)
        data = binary_data()
        record = Record(record_type, data, request_id)

        conn = Connection(self.sock)
        conn.write_record(record)

        self.sock.flip()

        record = conn.read_record()
        assert record.type == record_type
        assert record.content == data
        assert record.request_id == request_id

        assert conn.read_record() is None

    def test_read_write_long_content(self):
        data = binary_data(FCGI_MAX_CONTENT_LEN + 1)
        conn = Connection(self.sock)
        with self.assertRaises(ValueError):
            conn.write_record(Record(FCGI_STDERR, data, 1))

    def test_partial_read(self):
        conn = Connection(self.sock)

        data = binary_data(FCGI_RECORD_HEADER_LEN - 1)

        self.sock.sendall(data)

        self.sock.flip()

        self.assertRaises(PartialRead, conn.read_record)
