from __future__ import absolute_import

import unittest
from mock import Mock
import random

from ...const import (
    FCGI_RESPONDER,
    FCGI_AUTHORIZER,
    FCGI_FILTER,
    FCGI_KEEP_CONN,
    FCGI_BEGIN_REQUEST,
    FCGI_PARAMS,
    FCGI_ABORT_REQUEST,
    FCGI_END_REQUEST,
    FCGI_GET_VALUES,
    FCGI_GET_VALUES_RESULT,
    FCGI_REQUEST_COMPLETE,
    FCGI_CANT_MPX_CONN,
    FCGI_OVERLOADED,
    FCGI_UNKNOWN_ROLE,
    FCGI_MAX_CONNS,
    FCGI_MAX_REQS,
    FCGI_MPXS_CONNS,
    FCGI_NULL_REQUEST_ID,
)
from ...base import InputStream, Record
from ...utils import (
    pack_begin_request,
    pack_pairs,
    unpack_pairs,
    pack_end_request,
    unpack_end_request,
)


def random_request_id():
    return random.randint(1, 65535)


class ConnectionHandlerTests(unittest.TestCase):

    def test_send_record(self):
        from ...server import ConnectionHandler

        conn = Mock()
        record_type = FCGI_END_REQUEST
        content = pack_end_request(
            random.randint(0, 0xffffffff),
            random.choice((FCGI_REQUEST_COMPLETE, FCGI_CANT_MPX_CONN,
                           FCGI_OVERLOADED, FCGI_UNKNOWN_ROLE)))
        request_id = random_request_id()
        handler = ConnectionHandler(conn, None, None, None)

        handler.send_record(record_type, content, request_id)

        record = handler.conn.write_record.call_args[0][0]
        assert record.type == record_type
        assert record.content == content
        assert record.request_id == request_id

    def test_begin_request(self):
        request_id = random_request_id()
        handler = self.handler()

        self.begin_request(handler, request_id)

        assert request_id in handler.requests
        assert not handler.keep_open

    def test_begin_request_filter(self):
        request_id = random_request_id()
        handler = self.handler(role=FCGI_FILTER)

        self.begin_request(handler, request_id)

        assert isinstance(handler.requests[request_id].data, InputStream)

    def test_begin_request_keep_open(self):
        request_id = random_request_id()
        handler = self.handler()

        self.begin_request(handler, request_id, flags=FCGI_KEEP_CONN)

        assert handler.keep_open

    def test_begin_request_unknown_role(self):
        request_id = random_request_id()
        handler = self.handler()

        self.begin_request(handler, request_id, FCGI_AUTHORIZER)

        assert not handler.requests
        assert len(handler.records_sent) == 1
        record = handler.records_sent[0]
        assert record.type == FCGI_END_REQUEST
        assert record.request_id == request_id
        app_status, proto_status = unpack_end_request(record.content)
        assert proto_status == FCGI_UNKNOWN_ROLE

    def test_params(self):
        import os
        from ...server import Request

        env = os.environ.copy()
        conn = Mock()
        handler = self.handler()
        request = Request(conn, random_request_id(), handler.role)
        record = Record(FCGI_PARAMS, pack_pairs(env), request.id)

        handler.fcgi_params(record, request)
        record.content = ''
        handler.fcgi_params(record, request)

        assert request.environ == env

    def test_abort_request(self):
        from ...server import Request

        handler = self.handler()
        request = Request(None, random_request_id(), handler.role)
        handler.requests[request.id] = request
        record = Record(FCGI_ABORT_REQUEST, '', request.id)

        handler.fcgi_abort_request(record, request)

        assert len(handler.records_sent) == 1
        record = handler.records_sent[0]
        assert record.type == FCGI_END_REQUEST
        assert record.request_id == request.id
        assert not handler.requests

    def test_abort_request_running(self):
        from gevent import spawn, sleep
        from ...server import Request

        def handle_request(request):
            logger.debug('Request handler started')
            sleep(5)

        handler = self.handler(request_handler=handle_request)
        request = Request(Mock(), random_request_id(), handler.role)
        handler.requests[request.id] = request
        record = Record(FCGI_ABORT_REQUEST, '', request.id)

        handler._greenlet = spawn(handler._handle_request, request)
        sleep()
        handler.fcgi_abort_request(record, request)

        assert handler._greenlet.dead
        assert len(handler.records_sent) == 1
        record = handler.records_sent[0]
        assert record.type == FCGI_END_REQUEST
        assert record.request_id == request.id
        assert not handler.requests

    def test_get_values(self):
        server_caps = {
            FCGI_MAX_CONNS: 1,
            FCGI_MAX_REQS: 1,
            FCGI_MPXS_CONNS: 0,
        }
        handler = self.handler(capabilities=server_caps)
        request_caps = dict.fromkeys(server_caps, '')
        record = Record(FCGI_GET_VALUES, pack_pairs(request_caps), 0)

        handler.fcgi_get_values(record)

        response_caps = dict(unpack_pairs(''.join(
            record.content for record in handler.records_sent
            if record.type == FCGI_GET_VALUES_RESULT)))

        for cap in server_caps:
            assert cap in response_caps, repr(response_caps)
            assert isinstance(response_caps[cap], str)

    def test_run(self):
        handler = self.handler()

    def begin_request(self, handler, request_id, role=None, flags=0):

        if role is None:
            role = handler.role

        record = Record(FCGI_BEGIN_REQUEST,
                        pack_begin_request(role, flags), request_id)

        handler.fcgi_begin_request(record)

    def handler(self, role=FCGI_RESPONDER, capabilities={},
                request_handler=None):
        from ...server import ConnectionHandler

        class TestConnectionHandler(ConnectionHandler):
            def __init__(self, role=FCGI_RESPONDER, capabilities={},
                         request_handler=None):
                super(TestConnectionHandler, self).__init__(
                    Mock(), role, capabilities, request_handler)
                self.records_sent = []

            def send_record(self, record_type, content='',
                            request_id=FCGI_NULL_REQUEST_ID):
                self.records_sent.append(Record(record_type, content,
                                                request_id))

        return TestConnectionHandler(role, capabilities, request_handler)
