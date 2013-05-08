from __future__ import absolute_import

import os
import unittest

from gevent_fastcgi.const import (
    FCGI_ABORT_REQUEST,
    FCGI_AUTHORIZER,
    FCGI_BEGIN_REQUEST,
    FCGI_DATA,
    FCGI_END_REQUEST,
    FCGI_FILTER,
    FCGI_GET_VALUES,
    FCGI_GET_VALUES_RESULT,
    FCGI_KEEP_CONN,
    FCGI_MAX_CONNS,
    FCGI_MAX_REQS,
    FCGI_MPXS_CONNS,
    FCGI_PARAMS,
    FCGI_REQUEST_COMPLETE,
    FCGI_RESPONDER,
    FCGI_STDERR,
    FCGI_STDIN,
    FCGI_STDOUT,
    FCGI_UNKNOWN_ROLE,
    FCGI_UNKNOWN_TYPE,
    begin_request_struct,
    end_request_struct,
)
from gevent_fastcgi.base import (
    Record,
    pack_pairs,
    unpack_pairs,
)

from .utils import (
    WSGIApplication as app,
    start_wsgi_server,
    make_connection,
    Response,
    pack_env,
)


DATA = ''.join(map(chr, range(256)))


class ServerTests(unittest.TestCase):

    def test_address(self):
        unix_address = 'socket.%s' % (os.getpid(),)
        tcp_address = ('127.0.0.1', 47231)
        for address in (tcp_address, unix_address):
            with start_wsgi_server(address):
                with make_connection(address) as conn:
                    self._run_get_values(conn)

            # check if socket file was removed
            if isinstance(address, basestring):
                self.assertFalse(os.path.exists(address))

    def test_role(self):
        for role in (FCGI_RESPONDER, FCGI_FILTER, FCGI_AUTHORIZER):
            with start_wsgi_server(role=role) as server:
                with make_connection(server.address) as conn:
                    self._run_get_values(conn)

        for bad_role in (979897, 'sdfsdf', False):
            with self.assertRaises(ValueError):
                with start_wsgi_server(role=bad_role):
                    pass

    def test_unknown_record_type(self):
        with start_wsgi_server() as server:
            with make_connection(server.address) as conn:
                conn.write_record(Record(123))
                conn.done_writing()
                done = False
                for record in conn:
                    self.assertFalse(done)
                    self.assertEquals(record.type, FCGI_UNKNOWN_TYPE)
                    done = True
                self.assertTrue(done)

    def test_bad_request_id(self):
        with start_wsgi_server() as server:
            with make_connection(server.address) as conn:
                conn.write_record(Record(FCGI_ABORT_REQUEST, '', 1))
                conn.done_writing()
                self.assertIsNone(conn.read_record())

    def test_responder(self):
        request_id = 1
        request = (
            Record(FCGI_BEGIN_REQUEST,
                   begin_request_struct.pack(FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST', HTTPS='yes'),
                   request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, DATA, request_id),
            Record(FCGI_STDIN, '', request_id),
        )
        response = self._handle_one_request(request_id, request)
        self.assertEquals(response.request_status, FCGI_REQUEST_COMPLETE)

    def test_filter(self):
        request_id = 2
        request = [
            Record(FCGI_BEGIN_REQUEST,
                   begin_request_struct.pack(FCGI_FILTER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
            Record(FCGI_DATA, '', request_id),
        ]
        response = self._handle_one_request(
            request_id, request, role=FCGI_FILTER)
        self.assertEquals(response.request_status, FCGI_REQUEST_COMPLETE)

    def test_authorizer(self):
        request_id = 13
        request = [
            Record(FCGI_BEGIN_REQUEST,
                   begin_request_struct.pack(FCGI_AUTHORIZER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(), request_id),
            Record(FCGI_PARAMS, '', request_id),
        ]
        response = self._handle_one_request(
            request_id, request, role=FCGI_AUTHORIZER, app=app(response=''))
        self.assertEquals(response.request_status, FCGI_REQUEST_COMPLETE)

    def test_keep_conn(self):
        DATA = 'qwertyuiopasdfghjklzxcvbnm'
        requests = [
            # keep "connection" open
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                   FCGI_RESPONDER, FCGI_KEEP_CONN), 3),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 3),
            Record(FCGI_PARAMS, '', 3),
            Record(FCGI_STDIN, DATA, 3),
            Record(FCGI_STDIN, '', 3),
        ]

            # following requests should be served too
        for request_id in (4, 44, 444):
            requests += [
                Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                       FCGI_RESPONDER, 0), request_id),
                Record(FCGI_PARAMS,
                       pack_env(REQUEST_METHOD='POST'), request_id),
                Record(FCGI_PARAMS, '', request_id),
                Record(FCGI_STDIN, DATA, request_id),
                Record(FCGI_STDIN, '', request_id),
            ]
        for response in self._handle_requests((3, 4, 44, 444), requests):
            self.assertEquals(response.request_status, FCGI_REQUEST_COMPLETE)

    def test_wrong_role(self):
        request_id = 5
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                   FCGI_RESPONDER, 0), request_id),
        ]
        response = self._handle_one_request(
            request_id, request, role=FCGI_FILTER)
        self.assertEqual(response.request_status, FCGI_UNKNOWN_ROLE)

    def test_workers(self):
        with start_wsgi_server(num_workers=4) as server:
            self.assertEquals(server.num_workers, len(server.workers))

    def test_abort_request(self):
        request_id = 6
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                   FCGI_RESPONDER, 0), request_id),
            Record(FCGI_ABORT_REQUEST, '', request_id),
        ]
        response = self._handle_one_request(request_id, request)
        self.assertFalse(response.stdout.eof_received)
        self.assertFalse(response.stderr.eof_received)

        # let greenlet start after final FCGI_PARAMS then abort the request
        request_id = 7
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                   FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST', HTTPS='on'),
                   request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
            # make short delay!!!
            1,
            Record(FCGI_ABORT_REQUEST, '', request_id),
        ]
        # run slow_app to make sure server cannot complete request faster than
        # FCGI_ABORT_REQUEST "arrives"
        response = self._handle_one_request(request_id, request,
                                            app=app(delay=3))
        self.assertTrue(response.stdout.eof_received)
        headers, body = response.parse()
        self.assertTrue(headers.get('Status', '').startswith('500 '))

    def test_multiplexer(self):
        DATA = 'qwertyuiopasdfghjklzxcvbnm'
        requests = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                   FCGI_RESPONDER, 0), 8),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 8),
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                   FCGI_RESPONDER, 0), 9),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 9),
            Record(FCGI_PARAMS, '', 9),
            Record(FCGI_PARAMS, '', 8),
            Record(FCGI_STDIN, DATA, 9),
            Record(FCGI_STDIN, DATA, 8),
            Record(FCGI_STDIN, '', 9),
            Record(FCGI_STDIN, '', 8),
        ]
        for response in self._handle_requests((8, 9), requests):
            self.assertEqual(response.request_status, FCGI_REQUEST_COMPLETE)
            self.assertTrue(response.stdout.eof_received)
            headers, body = response.parse()
            self.assertTrue(headers.get('Status'), '200 OK')
            self.assertEqual(body, DATA)

    def test_failed_request(self):
        error = AssertionError('Mock application failure SIMULATION')
        request_id = 10
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                   FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
        ]
        response = self._handle_one_request(request_id, request,
                                            app=app(exception=error))
        self.assertTrue(response.stdout.eof_received)
        headers, body = response.parse()
        self.assertTrue(headers.get('Status', '').startswith('500 '))

        request_id = 11
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                   FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
        ]
        response = self._handle_one_request(request_id, request,
                                            app=app(delay=1, exception=error))

    def test_empty_response(self):
        request_id = 12
        request = [
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(
                   FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
        ]
        response = self._handle_one_request(request_id, request,
                                            app=app(response=''))
        self.assertTrue(response.stdout.eof_received)
        headers, body = response.parse()
        self.assertEquals(len(body), 0)

    # Helpers

    def _run_get_values(self, conn):
        names = (FCGI_MAX_CONNS, FCGI_MAX_REQS, FCGI_MPXS_CONNS)
        get_values_record = Record(FCGI_GET_VALUES, pack_pairs(
            dict.fromkeys(names, '')))

        conn.write_record(get_values_record)
        # signal we're done sending so server can exit reading loop
        # conn.done_writing()
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
        responses = dict(
            (request_id, Response(request_id)) for request_id in request_ids)

        with start_wsgi_server(**server_params) as server:
            with make_connection(server.address) as conn:
                map(conn.write_record, records)
                conn.done_writing()
                for record in conn:
                    self.assertIn(record.request_id, responses)
                    response = responses[record.request_id]
                    self.assertIs(response.request_status, None)
                    if record.type == FCGI_STDOUT:
                        response.stdout.feed(record.content)
                    elif record.type == FCGI_STDERR:
                        response.stderr.feed(record.content)
                    elif record.type == FCGI_END_REQUEST:
                        response.app_status, response.request_status = (
                            end_request_struct.unpack(record.content))
                        if response.request_status == FCGI_REQUEST_COMPLETE:
                            self.assertTrue(response.stdout.eof_received)
                            self.assertTrue(response.stderr.eof_received)
                    else:
                        self.fail('Unexpected record type %s' % record.type)

        return responses.values()
