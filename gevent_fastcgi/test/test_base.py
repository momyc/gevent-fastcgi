import unittest
import socket
from gevent_fastcgi.const import *


TEST_DATA = ''.join(map(chr, range(256)))


class RecordTests(unittest.TestCase):

    def test_bad_record(self):
        from gevent_fastcgi.base import Record

        self.assertRaises(ValueError, Record, 12345)


class StreamTests(unittest.TestCase):

    def test_input_stream(self):
        from gevent_fastcgi.base import InputStream

        MARK = 512
        stream = InputStream(max_mem=MARK)
        self.assertFalse(stream.landed)

        stream.feed('*' * MARK)
        self.assertFalse(stream.landed)

        stream.feed('-')
        self.assertTrue(stream.landed)

        stream.feed('')

        data = stream.read()
        self.assertEqual(data, '*' * MARK + '-')

        stream.feed('asdfghjkl\r' * 10)
        for line in stream:
            pass

        with self.assertRaises(AttributeError):
            stream.missing_attribute

    def test_output_stream(self):
        from gevent_fastcgi.base import Connection, OutputStream
        from gevent_fastcgi.test.utils import MockSocket

        sock = MockSocket()
        conn = Connection(sock)

        stdout = OutputStream(conn, 12345, FCGI_STDOUT)
        stdout.writelines(TEST_DATA for i in range(3))

        # writing empty string should not make it send anything
        sock.fail = True
        try:
            stdout.write('')
        except socket.error:
            self.fail('Writing empty string to output stream caused '
                      'write_record call')
        sock.fail = False

        stdout.close()

        with self.assertRaises(ValueError):
            stdout.write('sdfdsf')

        sock.flip()

        for i in range(3):
            in_rec = conn.read_record()
            self.assertEqual(in_rec.type, FCGI_STDOUT)
            self.assertEqual(in_rec.request_id, 12345)
            self.assertEqual(TEST_DATA, in_rec.content)

        in_rec = conn.read_record()
        self.assertEqual(in_rec.type, FCGI_STDOUT)
        self.assertEqual(in_rec.request_id, 12345)
        self.assertEqual('', in_rec.content)

        self.assertRaises(ValueError, stdout.write, 'sdfsfsd')

        self.assertTrue(str(stdout))


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
