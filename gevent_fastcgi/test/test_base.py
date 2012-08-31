import unittest
from gevent.hub import Waiter
from gevent_fastcgi.base import *
from gevent_fastcgi.test.utils import MockSocket


TEST_DATA = ''.join(map(chr, range(256)))


class SmallTests(unittest.TestCase):

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

    def test_read_write_records(self):
        sock = MockSocket()
        conn = Connection(sock)

        records = [Record(*params) for params in [
                (FCGI_GET_VALUES,),
                (FCGI_BEGIN_REQUEST, TEST_DATA, 731),
                (FCGI_STDIN, TEST_DATA * 8),
                ]]

        # write, read, compare
        for out_rec in records:
            conn.write_record(out_rec)
            sock.flip()
            in_rec = conn.read_record()
            self.assertEqual(out_rec, in_rec)

        # write all, then read and compare
        map(conn.write_record, records)
        sock.flip()
        in_records = list(iter(conn.read_record, None))
        self.assertEqual(records, in_records)
        
    def test_long_write(self):
        sock = MockSocket()
        conn = Connection(sock)
        long_data = TEST_DATA * 1024
        
        out_rec = Record(FCGI_STDIN, long_data, 123)
        conn.write_record(out_rec)
        sock.flip()

        clen = 0
        while True:
            in_rec = conn.read_record()
            if in_rec is None:
                break
            clen += len(in_rec.content)
        self.assertEqual(len(long_data), clen)

        with self.assertRaises(ValueError):
            conn.write_record(Record(FCGI_GET_VALUES, long_data))

    def test_partial_read(self):
        sock = MockSocket('1234')
        conn = Connection(sock)

        self.assertRaises(PartialRead, conn.read_record)



