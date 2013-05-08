import unittest
import socket
import random
import string
from gevent_fastcgi.const import (
    FCGI_GET_VALUES,
    FCGI_HEADER_LEN,
    FCGI_STDERR,
    FCGI_STDIN,
    FCGI_STDOUT,
)


def random_data(size, source=map(chr, xrange(256))):
    result = []
    remainder = size
    chunk_size = len(source)
    while remainder > 0:
        result.extend(random.sample(source, min(remainder, chunk_size)))
        remainder -= chunk_size
    return b''.join(result)


def random_line(size):
    return random_data(size, string.letters + string.digits
                       + string.punctuation) + '\r\n'


class RecordTests(unittest.TestCase):

    def test_bad_record(self):
        from gevent_fastcgi.base import Record

        self.assertRaises(ValueError, Record, 12345)


class InputStreamTests(unittest.TestCase):

    def make_one(self, *args, **kw):
        from gevent_fastcgi.base import InputStream

        return InputStream(*args, **kw)

    def test_feed_stream(self):
        data_in = random_data(2048)
        stream = self.make_one()
        stream.feed(data_in)
        stream.feed('')

        with self.assertRaises(IOError):
            stream.feed(random_data(1))

        with self.assertRaises(IOError):
            stream.feed('')

        data = stream.read()
        self.assertEqual(data, data_in)

    def test_iter(self):
        stream = self.make_one()
        data_in = [random_line(random.randint(1, 1024)) for _ in xrange(17)]

        map(stream.feed, data_in)
        stream.feed('')

        stream_iter = iter(stream)
        for line_in in data_in:
            line_out = stream_iter.next()
            self.assertEqual(line_in, line_out)

        with self.assertRaises(StopIteration):
            stream_iter.next()

    def test_blocks_until_eof(self):
        from gevent import Timeout

        stream = self.make_one()
        data = random_data(231)
        stream.feed(data)

        # no EOF mark was fed
        with self.assertRaises(Timeout):
            with Timeout(2):
                stream.read()

        # feed EOF makr
        stream.feed('')

        self.assertEqual(data, stream.read())


class OutputStreamTests(unittest.TestCase):

    def make_one(self, request_id=1, stream_type=FCGI_STDOUT):
        from gevent_fastcgi.base import Connection, OutputStream
        from gevent_fastcgi.test.utils import MockSocket

        conn = Connection(MockSocket())
        return OutputStream(conn, request_id, stream_type)

    def test_output_stream(self):
        request_id = 1293
        stream = self.make_one(request_id=request_id, stream_type=FCGI_STDERR)
        data_in = [random_line(random.randint(1, 1024)) for _ in xrange(13)]

        stream.writelines(data_in)

        conn = stream.conn
        sock = conn._sock

        # writing empty string should not make it send anything
        sock.fail = True
        try:
            stream.write('')
        except socket.error:
            self.fail('Writing empty string to output stream caused '
                      'write_record call')
        sock.fail = False

        stream.close()

        with self.assertRaises(ValueError):
            stream.write(random_data(1))

        sock.flip()

        for data in data_in:
            record = conn.read_record()
            self.assertEqual(record.type, stream.record_type)
            self.assertEqual(record.request_id, request_id)
            self.assertEqual(data, record.content)

        record = conn.read_record()
        self.assertEqual(record.type, stream.record_type)
        self.assertEqual(record.request_id, request_id)
        self.assertEqual('', record.content)

        self.assertRaises(ValueError, stream.write, random_data(1))


class ConnectionTests(unittest.TestCase):

    def test_write_long_content(self):
        from gevent_fastcgi.base import Record, Connection
        from gevent_fastcgi.test.utils import MockSocket

        sock = MockSocket()
        conn = Connection(sock)

        # this single record will be split into two at 0xfff8
        conn.write_record(Record(FCGI_STDIN, '*' * 0x10000, 1))
        self.assertEquals(len(sock.output), 8 + 8 + 0x10000)

    def test_too_long_content(self):
        from gevent_fastcgi.base import Record, Connection
        from gevent_fastcgi.test.utils import MockSocket

        sock = MockSocket()
        conn = Connection(sock)

        with self.assertRaises(ValueError):
            # Record of this type won't be split
            conn.write_record(Record(FCGI_GET_VALUES, '*' * 0x10000))

    def test_partial_read(self):
        from gevent_fastcgi.base import Connection, PartialRead
        from gevent_fastcgi.test.utils import MockSocket

        sock = MockSocket()
        sock.sendall('\0' * (FCGI_HEADER_LEN - 4))
        sock.flip()

        conn = Connection(sock)
        with self.assertRaises(PartialRead):
            conn.read_record()
