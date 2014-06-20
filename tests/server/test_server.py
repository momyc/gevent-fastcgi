from __future__ import absolute_import, with_statement

import os
import signal
import unittest
import logging


class Filter(logging.Filter):
    def filter(self, record):
        record.ppid = os.getppid()
        return 1

logging.getLogger().addFilter(Filter())


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
    FCGI_NULL_REQUEST_ID,
)
from gevent_fastcgi.base import Record
from gevent_fastcgi.utils import (
    pack_pairs, unpack_pairs, pack_begin_request, unpack_end_request)
from ..utils import (
    WSGIApplication as app,
    start_wsgi_server,
    make_connection,
    Response,
    pack_env,
    binary_data,
)


class ServerTests(unittest.TestCase):

    def test_address(self):
        unix_address = 'socket.{0}'.format(os.getpid())
        tcp_address = ('127.0.0.1', 47231)
        for address in (tcp_address, unix_address):
            with start_wsgi_server(address, num_workers=2):
                with make_connection(address) as conn:
                    self._run_get_values(conn)
            # check if socket file was removed
            if isinstance(address, basestring):
                assert not os.path.exists(address)

    def test_role(self):
        for role in (FCGI_RESPONDER, FCGI_FILTER, FCGI_AUTHORIZER):
            with start_wsgi_server(role=role) as server:
                with make_connection(server.address) as conn:
                    self._run_get_values(conn)

        for bad_role in (979897, -1):
            with self.assertRaises(ValueError):
                with start_wsgi_server(role=bad_role):
                    pass

    def test_unknown_request_id(self):
        with start_wsgi_server() as server:
            with make_connection(server.address) as conn:
                conn.write_record(Record(FCGI_ABORT_REQUEST, '', 1))
                conn.done_writing()
                assert conn.read_record() is None

    def test_responder(self):
        request_id = 1
        request = (
            Record(FCGI_BEGIN_REQUEST,
                   pack_begin_request(FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST', HTTPS='yes'),
                   request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, binary_data(), request_id),
            Record(FCGI_STDIN, '', request_id),
        )
        response = self._handle_one_request(request_id, request)
        assert response.request_status == FCGI_REQUEST_COMPLETE

    def test_filter(self):
        request_id = 2
        request = [
            Record(FCGI_BEGIN_REQUEST,
                   pack_begin_request(FCGI_FILTER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
            Record(FCGI_DATA, '', request_id),
        ]
        response = self._handle_one_request(
            request_id, request, role=FCGI_FILTER)
        assert response.request_status == FCGI_REQUEST_COMPLETE

    def test_authorizer(self):
        request_id = 13
        request = [
            Record(FCGI_BEGIN_REQUEST,
                   pack_begin_request(FCGI_AUTHORIZER, 0), request_id),
            Record(FCGI_PARAMS, pack_env(), request_id),
            Record(FCGI_PARAMS, '', request_id),
        ]
        response = self._handle_one_request(
            request_id, request, role=FCGI_AUTHORIZER, app=app(response=''))
        assert response.request_status == FCGI_REQUEST_COMPLETE

    def test_keep_conn(self):
        data = binary_data()
        requests = [
            # keep "connection" open
            Record(FCGI_BEGIN_REQUEST, pack_begin_request(
                   FCGI_RESPONDER, FCGI_KEEP_CONN), 3),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 3),
            Record(FCGI_PARAMS, '', 3),
            Record(FCGI_STDIN, data, 3),
            Record(FCGI_STDIN, '', 3),
        ]

        # following requests should be served too
        for request_id in (4, 44, 444):
            requests += [
                Record(FCGI_BEGIN_REQUEST, pack_begin_request(
                       FCGI_RESPONDER, 0), request_id),
                Record(FCGI_PARAMS,
                       pack_env(REQUEST_METHOD='POST'), request_id),
                Record(FCGI_PARAMS, '', request_id),
                Record(FCGI_STDIN, data, request_id),
                Record(FCGI_STDIN, '', request_id),
            ]
        for response in self._handle_requests((3, 4, 44, 444), requests):
            assert response.request_status == FCGI_REQUEST_COMPLETE

    def test_wrong_role(self):
        request_id = 5
        request = [
            Record(FCGI_BEGIN_REQUEST, pack_begin_request(
                   FCGI_RESPONDER, 0), request_id),
        ]
        response = self._handle_one_request(
            request_id, request, role=FCGI_FILTER)
        assert response.request_status == FCGI_UNKNOWN_ROLE

    def test_abort_request(self):
        request_id = 6
        request = [
            Record(FCGI_BEGIN_REQUEST, pack_begin_request(
                   FCGI_RESPONDER, 0), request_id),
            Record(FCGI_ABORT_REQUEST, '', request_id),
        ]
        response = self._handle_one_request(request_id, request)
        assert response.request_status == FCGI_REQUEST_COMPLETE

    def test_multiplexer(self):
        data = binary_data()
        requests = [
            Record(FCGI_BEGIN_REQUEST, pack_begin_request(
                   FCGI_RESPONDER, 0), 8),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 8),
            Record(FCGI_BEGIN_REQUEST, pack_begin_request(
                   FCGI_RESPONDER, 0), 9),
            Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='POST'), 9),
            Record(FCGI_PARAMS, '', 9),
            Record(FCGI_PARAMS, '', 8),
            Record(FCGI_STDIN, data, 9),
            Record(FCGI_STDIN, data, 8),
            Record(FCGI_STDIN, '', 9),
            Record(FCGI_STDIN, '', 8),
        ]
        for response in self._handle_requests((8, 9), requests):
            assert response.request_status == FCGI_REQUEST_COMPLETE
            assert response.stdout.eof_received
            headers, body = response.parse()
            assert headers.get('Status') == '200 OK', repr(headers)
            assert body == data

    def test_failed_request(self):
        error = AssertionError('Mock application failure SIMULATION')
        request_id = 10
        request = [
            Record(FCGI_BEGIN_REQUEST, pack_begin_request(
                   FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
        ]
        response = self._handle_one_request(request_id, request,
                                            app=app(exception=error))
        assert response.stdout.eof_received
        headers, body = response.parse()
        assert headers.get('Status', '').startswith('500 ')

        request_id = 11
        request = [
            Record(FCGI_BEGIN_REQUEST, pack_begin_request(
                   FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
        ]
        response = self._handle_one_request(request_id, request,
                                            app=app(delay=1, exception=error))

    def test_empty_response(self):
        request_id = 12
        request = [
            Record(FCGI_BEGIN_REQUEST, pack_begin_request(
                   FCGI_RESPONDER, 0), request_id),
            Record(FCGI_PARAMS, '', request_id),
            Record(FCGI_STDIN, '', request_id),
        ]
        response = self._handle_one_request(request_id, request,
                                            app=app(response=''))
        assert response.stdout.eof_received
        headers, body = response.parse()
        assert len(body) == 0, repr(body)

    def test_restart_workers(self):
        from gevent import sleep

        with start_wsgi_server(num_workers=4) as server:
            assert server.num_workers == 4
            workers = server._workers
            assert len(workers) == server.num_workers
            worker = workers[2]
            os.kill(worker, signal.SIGKILL)
            sleep(0.1)
            try:
                os.kill(worker, 0)
            except OSError, e:
                assert e.errno == errno.ESRCH
            sleep(5)
            assert len(server._workers) == server.num_workers
            assert worker not in server._workers

    # Helpers

    def _run_get_values(self, conn):
        names = (FCGI_MAX_CONNS, FCGI_MAX_REQS, FCGI_MPXS_CONNS)
        get_values_record = Record(FCGI_GET_VALUES,
                                   pack_pairs(dict.fromkeys(names, '')),
                                   FCGI_NULL_REQUEST_ID)

        conn.write_record(get_values_record)
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
        responses = dict(
            (request_id, Response(request_id)) for request_id in request_ids)

        with start_wsgi_server(**server_params) as server:
            with make_connection(server.address) as conn:
                map(conn.write_record, records)
                conn.done_writing()
                for record in conn:
                    self.assertIn(record.request_id, responses)
                    response = responses[record.request_id]
                    self.assertIs(response.request_status, None, str(record))
                    if record.type == FCGI_STDOUT:
                        response.stdout.feed(record.content)
                    elif record.type == FCGI_STDERR:
                        response.stderr.feed(record.content)
                    elif record.type == FCGI_END_REQUEST:
                        response.app_status, response.request_status = (
                            unpack_end_request(record.content))
                    else:
                        self.fail('Unexpected record type %s' % record.type)

        return responses.values()
