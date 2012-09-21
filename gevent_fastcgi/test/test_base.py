import unittest
from gevent.hub import Waiter
from gevent_fastcgi.base import *
from gevent_fastcgi.test.utils import MockSocket


TEST_DATA = ''.join(map(chr, range(256)))


class RecordTests(unittest.TestCase):

    def test_bad_record(self):
        self.assertRaises(ValueError, Record, 12345)


class StreamTests(unittest.TestCase):

    def test_input_stream(self):
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

        with self.assertRaises(AttributeError):
            stream.missing_attribute

    def test_output_stream(self):
        sock = MockSocket()
        conn = Connection(sock)

        stdout = OutputStream(conn, 12345, FCGI_STDOUT)
        stdout.write(TEST_DATA)

        # writing empty string should not make it send anything
        sock.fail = True
        try:
            stdout.write('')
        except socket.error, e:
            self.fail('Writing empty string to output stream caused write_record call')
        sock.fail = False

        stdout.close()

        sock.flip()

        in_rec = conn.read_record()
        self.assertEqual(in_rec.type, FCGI_STDOUT)
        self.assertEqual(in_rec.request_id, 12345)
        self.assertEqual(TEST_DATA, in_rec.content)

        in_rec = conn.read_record()
        self.assertEqual(in_rec.type, FCGI_STDOUT)
        self.assertEqual(in_rec.request_id, 12345)
        self.assertEqual('', in_rec.content)

        self.assertRaises(socket.error, stdout.write, 'sdfsfsd')

        self.assertTrue(str(stdout))


class ConnectionTests(unittest.TestCase):

    def test_write_long_content(self):
        sock = MockSocket()
        conn = Connection(sock)

        # this single record will be split into two at 0xfff8
        conn.write_record(Record(FCGI_STDIN, '*' * 0x10000, 1))
        self.assertEquals(len(sock.output), 8 + 8 + 0x10000)

    def test_too_long_content(self):
        sock = MockSocket()
        conn = Connection(sock)

        with self.assertRaises(ValueError):
            # Record of this type won't be split
            conn.write_record(Record(FCGI_GET_VALUES, '*' * 0x10000))

