import os
import unittest

from gevent_fastcgi.base import (
    FCGI_RESPONDER,
    FCGI_FILTER,
    FCGI_AUTHORIZER,
    FCGI_BEGIN_REQUEST,
    FCGI_END_REQUEST,
    FCGI_ABORT_REQUEST,
    FCGI_PARAMS,
    FCGI_STDIN,
    FCGI_STDOUT,
    FCGI_STDERR,
    FCGI_DATA,
    FCGI_GET_VALUES,
    FCGI_GET_VALUES_RESULT,
    FCGI_REQUEST_COMPLETE,
    FCGI_KEEP_CONN,
    FCGI_UNKNOWN_TYPE,
    FCGI_UNKNOWN_ROLE,
    FCGI_MAX_CONNS,
    FCGI_MAX_REQS,
    FCGI_MPXS_CONNS,
    Record,
    begin_request_struct,
    end_request_struct,
    pack_pairs,
    unpack_pairs,
)

from gevent_fastcgi.test.utils import (
    app,
    slow_app,
    echo_app,
    failing_app,
    failing_app2,
    empty_app,
    pack_env,
    make_server,
    make_connection,
    make_server_conn,
)


ADDRESS = ('127.0.0.1', 49281)
DATA = ''.join(map(chr, range(256))) * 1024


class ServerTests(unittest.TestCase):

    def test_address(self):
        unix_socket = 'socket.%s-%s' % (os.getppid(), os.getpid())
        for address in [('127.0.0.1', 47231), unix_socket]:
            with make_server_conn(address) as conn:
                self._run_get_values(conn)
            if address == unix_socket:
                self.assertFalse(os.path.exists(address))

    def test_role(self):
        for role in ('responder', 'ResPonDer', 'filter', 'authorizer', FCGI_RESPONDER, FCGI_FILTER, FCGI_AUTHORIZER):
            with make_server_conn(role=role) as conn:
                self._run_get_values(conn)

        for bad_role in (979897, 'sdjflskdfj'):
            with self.assertRaises(ValueError):
                with make_server(role=bad_role):
                    pass

    def test_workers(self):
        with make_server(num_workers=3) as server:
            self.assertEqual(len(server.workers), 3)
        
        for bad_num in (0, -10):
            with self.assertRaises(ValueError):
                make_server(num_workers=bad_num)

        # 1 worker does not spawn anything
        with make_server(num_workers=1) as server:
            self.assertEqual(0, len(server.workers))

    def test_unknown_record_type(self):
        with make_server_conn() as conn:
            conn.write_record(Record(123))
            conn.done_writing()
            done = False
            for record in conn:
                self.assertFalse(done)
                self.assertEquals(record.type, FCGI_UNKNOWN_TYPE)
                done = True

    def test_bad_request_id(self):
        with make_server_conn() as conn:
            conn.write_record(Record(FCGI_ABORT_REQUEST, '', 666))
            self.assertIs(conn.read_record(), None)

    def test_responder(self):
        request_id = 1
        request = (
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, DATA, request_id),
            Record(FCGI_STDIN, '', request_id),
        )
        response = self._handle_one_request(request_id, request)
        self.assertEquals(response.request_status, FCGI_REQUEST_COMPLETE)
        self.assertTrue(response.stdout_closed)
        self.assertTrue(response.stderr_closed)

    def test_filter(self):
        request_id = 2
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_FILTER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
            Record(FCGI_DATA, '', request_id),
            ]
        response = self._handle_one_request(request_id, request, address='asdasdasd', role=FCGI_FILTER)
        self.assertEquals(response.request_status, FCGI_REQUEST_COMPLETE)
        self.assertTrue(response.stdout_closed)
        self.assertTrue(response.stderr_closed)

    def test_authorizer(self):
        request_id = 13
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_AUTHORIZER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(), request_id),
            Record(FCGI_PARAMS, '', request_id),
            ]
        response = self._handle_one_request(request_id, request, app=empty_app, role=FCGI_AUTHORIZER)
        self.assertEquals(response.request_status, FCGI_REQUEST_COMPLETE)
        self.assertTrue(response.stdout_closed)
        self.assertTrue(response.stderr_closed)

    def test_multiple_requests(self):
        requests = [
            # keep "connection" open after first request is processed
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, FCGI_KEEP_CONN), 3),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 3),
            Record(FCGI_PARAMS, '', 3),
            Record(FCGI_STDIN, DATA, 3),
            Record(FCGI_STDIN, '', 3),
            # and after this one connection supposed to be closed by 
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 4),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 4),
            Record(FCGI_PARAMS, '', 4),
            Record(FCGI_STDIN, DATA, 4),
            Record(FCGI_STDIN, '', 4),
            ]
        for response in self._handle_requests((3, 4), requests):
            self.assertEquals(response.request_status, FCGI_REQUEST_COMPLETE)
            self.assertTrue(response.stdout_closed)
            self.assertTrue(response.stderr_closed)

    def test_wrong_role(self):
        request_id = 5
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
            ]
        response = self._handle_one_request(request_id, request, role=FCGI_FILTER)
        self.assertEqual(response.request_status, FCGI_UNKNOWN_ROLE)

    def test_abort_request(self):
        request_id = 6
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), request_id),
            Record(FCGI_ABORT_REQUEST, '', request_id),
            ]
        response = self._handle_one_request(request_id, request)
        self.assertIs(response.stdout, None)
        self.assertIs(response.stderr, None)

        # let greenlet start after final FCGI_PARAMS then abort the request
        request_id = 7
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST', HTTPS='on'), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
            # make short delay!!!
            0.5,
            Record(FCGI_ABORT_REQUEST, '', request_id),
            ]
        # run slow_app to make sure server cannot complete request faster than FCGI_ABORT_REQUEST "arrives"
        response = self._handle_one_request(request_id, request, app=slow_app)
        if response.stdout is not None:
            self.assertTrue(response.stdout.startswith('Status: 500 '))
        if response.stdout is not None:
            self.assertTrue(response.stderr.startswith('Traceback (most recent call last):'))

    def test_multiplexer(self):
        requests = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 8),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 8),
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 9),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 9),
            Record(FCGI_PARAMS, '', 9),
            Record(FCGI_PARAMS, '', 8),
            Record(FCGI_STDIN, DATA, 9),
            Record(FCGI_STDIN, DATA, 8),
            Record(FCGI_STDIN, '', 9),
            Record(FCGI_STDIN, '', 8),
            ]
        for response in self._handle_requests((8, 9), requests, app=echo_app):
            self.assertEqual(response.request_status, FCGI_REQUEST_COMPLETE)
            self.assertTrue(response.stdout_closed and response.stderr_closed)
            self.assertTrue(response.stdout.startswith('Status: 200 OK\r\n\r\n'))
            self.assertEqual(len(response.stdout) - 18, len(DATA))

    def test_failed_request(self):
        request_id = 10
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
            ]
        response = self._handle_one_request(request_id, request, app=failing_app)
        self.assertTrue(response.stdout.startswith('Status: 500 Internal Server Error'))
        self.assertTrue(response.stderr.startswith('Traceback (most recent call last):'))

        request_id = 11
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
            ]
        response = self._handle_one_request(request_id, request, app=failing_app2)
        print response.stdout
        print '*' * 100
        print response.stderr

    def test_empty_response(self):
        request_id = 12
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
            ]
        response = self._handle_one_request(request_id, request, app=empty_app)
        self.assertEquals(response.stdout, 'Status: 200 OK\r\n\r\n')
        self.assertEquals(response.stderr, '')

    # Helpers

    def _run_get_values(self, conn):
        names = (FCGI_MAX_CONNS, FCGI_MAX_REQS, FCGI_MPXS_CONNS)
        get_values_record = Record(FCGI_GET_VALUES, pack_pairs(dict.fromkeys(names, '')))

        conn.write_record(get_values_record)
        # signal we're done sending so server can exit reading loop
        conn.done_writing()
        done = False
        for record in conn:
            self.assertFalse(done)
            self.assertEquals(record.type, FCGI_GET_VALUES_RESULT)
            values = dict(unpack_pairs(record.content))
            for name in names:
                self.assertIn(name, values)
            done = True

    def _handle_one_request(self, request_id, records, **server_params):
        return self._handle_requests([request_id], records, **server_params)[0]

    def _handle_requests(self, request_ids, records, **server_params):
        responses = dict((request_id, Response(request_id)) for request_id in request_ids)
        
        with make_server_conn(**server_params) as conn:
            map(conn.write_record, records)
            conn.done_writing()

            for record in conn:
                self.assertIn(record.request_id, responses)
                response = responses[record.request_id]
                self.assertIs(response.request_status, None)
                if record.type == FCGI_STDOUT:
                    self.assertFalse(response.stdout_closed)
                    if response.stdout is None:
                        response.stdout = record.content
                    else:
                        response.stdout += record.content
                    if not record.content:
                        response.stdout_closed = True
                elif record.type == FCGI_STDERR:
                    self.assertFalse(response.stderr_closed)
                    if response.stderr is None:
                        response.stderr = record.content
                    else:
                        response.stderr += record.content
                    if not record.content:
                        response.stderr_closed = True
                elif record.type == FCGI_END_REQUEST:
                    response.app_status, response.request_status = end_request_struct.unpack(record.content)
                else:
                    self.fail('Unexpected record type %s' % record.type)

        return responses.values()


class Response(object):

    def __init__(self, request_id):
        self.request_id = request_id
        self.stdout = None
        self.stdout_closed = False
        self.stderr = None
        self.stderr_closed = False
        self.request_status = None
        self.app_status = None
