import unittest

from gevent_fastcgi.base import *
from gevent_fastcgi.server import WSGIServer, ServerConnection
from gevent_fastcgi.test.utils import MockSocket


ADDRESS = ('127.0.0.1', 18374)
DATA = ''.join(map(chr, range(256))) * 1024
ENVIRON = {
        'SCRIPT_NAME': '',
        'PATH_INFO': '/',
        'REQUEST_METHOD': 'GET',
        'QUERY_STRING': '',
        'CONTENT_TYPE': 'text/plain',
        'SERVER_NAME': '127.0.0.1',
        'SERVER_PORT': '80',
        'SERVER_PROTOCOL': 'HTTP/1.0',
        }

def pack_env(**kw):
    env = dict(ENVIRON)
    env.update(kw)
    return pack_pairs(env)

def app(environ, start_response):
    start_response('200 OK', [])
    return ['OK']

def slow_app(environ, start_response):
    from gevent import sleep

    start_response('200 OK', [])
    sleep(0.5)
    return ['OK']

def echo_app(environ, start_response):
    start_response('200 OK', [])
    data = environ['wsgi.input'].read()
    write(data)
    return [data]


class ServerTests(unittest.TestCase):

    def test_address(self):
        for address in [('127.0.0.1', 47231), 'socket']:
            self.start_server(address).stop()

    def test_role(self):
        for role in ('responder', 'ResPonDer', 'filter', 'authorizer', FCGI_RESPONDER, FCGI_FILTER, FCGI_AUTHORIZER):
            self.start_server(role=role).stop()

        for bad_role in (979897, 'sdjflskdfj'):
            with self.assertRaises(ValueError):
                self.start_server(role=bad_role)

    def test_workers(self):
        server = self.start_server(num_workers=3)
        server.start()
        self.assertEqual(len(server.workers), 3)
        server.stop()
        
        for bad_num in (0, -10):
            with self.assertRaises(ValueError):
                self.start_server(num_workers=bad_num)

    def test_bad_record(self):
        recs = self.handle_records(Record(193))
        self.assertEqual(1, len(recs))
        self.assertEqual(recs[0].type, FCGI_UNKNOWN_TYPE)

    def test_request_id(self):
        recs = self.handle_records(Record(FCGI_ABORT_REQUEST, request_id=123))
        self.assertFalse(recs)

    def test_get_values(self):
        caps = (FCGI_MAX_CONNS, FCGI_MPXS_CONNS)
        content = pack_pairs(((name, '') for name in caps))
        recs = self.handle_records(Record(FCGI_GET_VALUES, content))

        self.assertEqual(1, len(recs))

        rec = recs[0]
        self.assertEqual(rec.type, FCGI_GET_VALUES_RESULT)

        values = dict(unpack_pairs(rec.content))
        for name in caps:
            self.assertIn(name, values)
            self.assertTrue(isinstance(values[name], basestring))

    def test_responder(self):
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 31),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 31),
            Record(FCGI_PARAMS, '', 31),
            Record(FCGI_STDIN, DATA, 31),
            Record(FCGI_STDIN, '', 31),
            ]
        self.handle_records(request)

    def test_filter(self):
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_FILTER, 0), 1),
            Record(FCGI_PARAMS, '', 1),
            Record(FCGI_STDIN, '', 1),
            Record(FCGI_DATA, '', 1),
            ]
        self.handle_records(request, role=FCGI_FILTER)

    def test_wrong_role(self):
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 31),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 31),
            Record(FCGI_PARAMS, '', 31),
            Record(FCGI_STDIN, DATA, 31),
            Record(FCGI_STDIN, '', 31),
            ]
        self.handle_records(request, role=FCGI_FILTER)

    def test_abort_request(self):
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 2),
            Record(FCGI_ABORT_REQUEST, '', 2),
            ]
        self.handle_records(request)

        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 2),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 2),
            Record(FCGI_PARAMS, '', 2),
            Record(FCGI_STDIN, DATA, 2),
            Record(FCGI_STDIN, '', 2),
            Record(FCGI_ABORT_REQUEST, '', 2),
            ]
        self.handle_records(request, app=slow_app)

    def test_multiplexer(self):
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 1),
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 2),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 1),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 2),
            Record(FCGI_PARAMS, '', 2),
            Record(FCGI_PARAMS, '', 1),
            Record(FCGI_STDIN, DATA, 1),
            Record(FCGI_STDIN, DATA, 2),
            Record(FCGI_STDIN, '', 2),
            Record(FCGI_STDIN, '', 1),
            ]
        self.handle_records(request, app=echo_app)

    def start_server(self, address=ADDRESS, app=app, **kw):
        server = WSGIServer(address, app, **kw)
        self._servers.append(server)
        return server

    def handle_records(self, records, **kw):
        # serialize records
        sock = MockSocket()
        conn = Connection(sock, 1024)
        if isinstance(records, Record):
            records = [records]
        map(conn.write_record, records)

        # move serialized records into socket's input buffer
        sock.flip()

        server = self.start_server(**kw)
        server.handle_connection(sock, '<fake-peer>')
        server.stop()

        # read server response
        sock.flip()
        return list(iter(conn.read_record, None))

    def setUp(self):
        self._servers = []

    def tearDown(self):
        for server in self._servers:
            server.stop()
