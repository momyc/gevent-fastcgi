from __future__ import absolute_import

import unittest
import random

from ...base import InputStream, Record
from ...utils import (
    pack_begin_request,
    pack_pairs,
    unpack_pairs,
    unpack_end_request,
)
from ...const import (
    FCGI_RESPONDER,
    FCGI_NULL_REQUEST_ID,
)

try:
    from ...server import ConnectionHandler, ServerConnection
except ImportError:
    logger.exception('Failed to import classes')

    class TestConnectionHandler(object):
        pass
else:
    class TestConnectionHandler(ConnectionHandler):
        """ ConnectionHandler that intersepts send_record calls.

        It also has some handy methods used by tests
        """
        def __init__(self, conn=None, role=FCGI_RESPONDER, capabilities={},
                     request_handler=None):
            from ..utils import MockSocket

            if conn is None:
                conn = ServerConnection(MockSocket())
            if request_handler is None:
                request_handler = self.default_request_handler
            ConnectionHandler.__init__(
                self, conn, role, capabilities, request_handler)
            self.records_sent = []

        def send_record(self, record_type, content='',
                        request_id=FCGI_NULL_REQUEST_ID):
            self.records_sent.append(Record(record_type, content,
                                            request_id))

        def begin_request(self, request_id=None, role=None, flags=0):
            from ...const import FCGI_BEGIN_REQUEST

            if request_id is None:
                request_id = random_request_id()
            if role is None:
                role = self.role
            record = Record(FCGI_BEGIN_REQUEST,
                            pack_begin_request(role, flags), request_id)
            self.handle_begin_request_record(record)

            return self.requests.get(request_id)

        @staticmethod
        def default_request_handler(request):
            pass


def random_request_id():
    return random.randint(1, 65535)


class ConnectionHandlerTests(unittest.TestCase):

    def test_send_record(self):
        from ...const import (FCGI_GET_VALUES, FCGI_MAX_CONNS, FCGI_MAX_REQS,
                              FCGI_MPXS_CONNS)

        record_type = FCGI_GET_VALUES
        content = pack_pairs((
            (FCGI_MAX_CONNS, ''),
            (FCGI_MAX_REQS, ''),
            (FCGI_MPXS_CONNS, ''),
        ))
        handler = TestConnectionHandler()

        handler.send_record(record_type, content, FCGI_NULL_REQUEST_ID)

        assert len(handler.records_sent) == 1
        record = handler.records_sent[0]
        assert record.type == record_type
        assert record.content == content
        assert record.request_id == FCGI_NULL_REQUEST_ID

    def test_begin_request(self):
        handler = TestConnectionHandler()
        request = handler.begin_request()

        assert len(handler.requests) == 1
        assert request.id in handler.requests
        assert not handler.keep_open

    def test_begin_filter_request(self):
        from ...const import FCGI_FILTER

        handler = TestConnectionHandler(role=FCGI_FILTER)
        request = handler.begin_request()

        assert isinstance(request.data, InputStream)

    def test_begin_request_keep_open(self):
        from ...const import FCGI_ABORT_REQUEST, FCGI_KEEP_CONN

        handler = TestConnectionHandler()
        request = handler.begin_request(flags=FCGI_KEEP_CONN)
        handler.handle_abort_request_record(
            Record(FCGI_ABORT_REQUEST, '', request.id), request)

        assert not handler.requests
        assert handler.conn._sock is not None, (
            'Connection was closed despite FCGI_KEEP_CONN flag')

    def test_begin_request_unknown_role(self):
        from ...const import (
            FCGI_RESPONDER,
            FCGI_AUTHORIZER,
            FCGI_NULL_REQUEST_ID,
            FCGI_END_REQUEST,
            FCGI_UNKNOWN_ROLE,
        )

        handler = TestConnectionHandler(role=FCGI_RESPONDER)
        request = handler.begin_request(role=FCGI_AUTHORIZER)

        assert request is None
        assert len(handler.records_sent) == 1
        record = handler.records_sent[0]
        assert record.type == FCGI_END_REQUEST
        assert record.request_id != FCGI_NULL_REQUEST_ID
        app_status, proto_status = unpack_end_request(record.content)
        assert proto_status == FCGI_UNKNOWN_ROLE

    def test_params(self):
        import os
        from ...const import FCGI_PARAMS

        env = os.environ.copy()
        handler = TestConnectionHandler()
        request = handler.begin_request()
        record = Record(FCGI_PARAMS, pack_pairs(env), request.id)

        handler.handle_params_record(record, request)
        record = Record(FCGI_PARAMS, '', request.id)
        handler.handle_params_record(record, request)

        assert request.environ == env

    def test_abort_request(self):
        from ...const import FCGI_ABORT_REQUEST, FCGI_END_REQUEST

        handler = TestConnectionHandler()
        request = handler.begin_request()
        record = Record(FCGI_ABORT_REQUEST, '', request.id)

        handler.handle_abort_request_record(record, request)

        assert not handler.requests
        assert len(handler.records_sent) == 1
        record = handler.records_sent[0]
        assert record.type == FCGI_END_REQUEST
        assert record.request_id == request.id

    def test_abort_request_running(self):
        from gevent import sleep, event
        from ...const import (
            FCGI_PARAMS, FCGI_STDIN, FCGI_ABORT_REQUEST, FCGI_END_REQUEST)

        lock = event.Event()

        def handle_request(request):
            lock.set()
            sleep(3)

        handler = TestConnectionHandler(role=FCGI_RESPONDER,
                                        request_handler=handle_request)
        request = handler.begin_request()
        # next records should spawn request handler
        handler.handle_params_record(
            Record(FCGI_PARAMS, '', request.id), request)
        handler.handle_stdin_record(
            Record(FCGI_STDIN, '', request.id), request)
        # let it actually start
        lock.wait(3)

        record = Record(FCGI_ABORT_REQUEST, '', request.id)
        handler.handle_abort_request_record(record, request)

        assert request.greenlet.dead
        assert len(handler.records_sent) == 1
        record = handler.records_sent[0]
        assert record.type == FCGI_END_REQUEST
        assert record.request_id == request.id
        assert not handler.requests

    def test_get_values(self):
        from ...const import (
            FCGI_MAX_CONNS, FCGI_MAX_REQS, FCGI_MPXS_CONNS, FCGI_GET_VALUES,
            FCGI_GET_VALUES_RESULT)

        server_caps = {
            FCGI_MAX_CONNS: 1,
            FCGI_MAX_REQS: 1,
            FCGI_MPXS_CONNS: 0,
        }
        handler = TestConnectionHandler(capabilities=server_caps)
        request_caps = dict.fromkeys(server_caps, '')
        record = Record(FCGI_GET_VALUES, pack_pairs(request_caps), 0)

        handler.handle_get_values_record(record)

        response_caps = dict(unpack_pairs(''.join(
            record.content for record in handler.records_sent
            if record.type == FCGI_GET_VALUES_RESULT)))

        for cap in server_caps:
            assert cap in response_caps, repr(response_caps)
            assert isinstance(response_caps[cap], str)
