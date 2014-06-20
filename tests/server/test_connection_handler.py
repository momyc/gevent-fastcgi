from __future__ import absolute_import

import unittest
import mock
from itertools import count

from gevent import sleep, spawn, event

from gevent_fastcgi.const import (
    FCGI_RESPONDER,
    FCGI_FILTER,
    FCGI_AUTHORIZER,
    FCGI_MAX_CONNS,
    FCGI_MAX_REQS,
    FCGI_MPXS_CONNS,
    FCGI_NULL_REQUEST_ID,
    FCGI_KEEP_CONN,
    FCGI_GET_VALUES,
    FCGI_GET_VALUES_RESULT,
    FCGI_BEGIN_REQUEST,
    FCGI_END_REQUEST,
    FCGI_ABORT_REQUEST,
    FCGI_UNKNOWN_ROLE,
    FCGI_UNKNOWN_TYPE,
    FCGI_PARAMS,
    FCGI_STDIN,
    FCGI_STDOUT,
    FCGI_STDERR,
    FCGI_DATA,
)
from gevent_fastcgi.base import InputStream, Record
from gevent_fastcgi.utils import (
    pack_begin_request,
    pack_pairs,
    unpack_pairs,
    unpack_end_request,
    unpack_unknown_type,
)
from gevent_fastcgi.server import ConnectionHandler, ServerConnection
from ..utils import pack_env


class ConnectionHandlerTests(unittest.TestCase):

    def test_unknown_request(self):
        records = (
            (FCGI_STDIN, '', next_req_id()),
            (FCGI_ABORT_REQUEST, '', next_req_id()),
            (FCGI_PARAMS, pack_env(), next_req_id()),
            (FCGI_DATA, 'data', next_req_id()),
        )

        for rec in records:
            handler = run_handler((rec,))
            conn = handler.conn

            assert conn.close.called
            assert not read_records(conn)
            assert not handler.requests
            assert not handler.request_handler.called

    def test_unknown_record_type(self):
        rec_type = 123
        records = (
            (rec_type, ),
        )

        handler = run_handler(records)

        rec = find_rec(handler, FCGI_UNKNOWN_TYPE)
        assert rec and unpack_unknown_type(rec.content)

    def test_get_values(self):
        req_id = next_req_id
        records = (
            (FCGI_GET_VALUES, pack_pairs(
                (name, '') for name in (
                    FCGI_MAX_CONNS,
                    FCGI_MAX_REQS,
                    FCGI_MPXS_CONNS,
                )
            )),
        )

        handler = run_handler(records)

        assert not handler.requests
        assert not handler.request_handler.called
        assert handler.conn.close.called

        rec = find_rec(handler, FCGI_GET_VALUES_RESULT)
        assert rec
        assert unpack_pairs(rec.content)

    def test_request(self):
        req_id = next_req_id()
        role = FCGI_RESPONDER
        flags = 0
        records = (
            (FCGI_BEGIN_REQUEST, pack_begin_request(role, flags), req_id),
            (FCGI_PARAMS, pack_env(), req_id),
            (FCGI_PARAMS, '', req_id),
        )

        handler = run_handler(records, role=role)

        assert not handler.requests
        assert handler.request_handler.call_count == 1
        assert handler.conn.close.called

        rec = find_rec(handler, FCGI_END_REQUEST, req_id)
        assert rec and unpack_end_request(rec.content)

        for stream in FCGI_STDOUT, FCGI_STDERR:
            assert '' == read_stream(handler, stream, req_id)

    def test_abort_request(self):
        req_id = next_req_id()
        role = FCGI_RESPONDER
        flags = 0
        records = (
            (FCGI_BEGIN_REQUEST, pack_begin_request(role, flags), req_id),
            (FCGI_PARAMS, pack_env(), req_id),
            (FCGI_PARAMS, '', req_id),
            # request_handler gets spawned after PARAMS is "closed"
            # lets give it a chance to run
            0.1,
            # then abort it
            (FCGI_ABORT_REQUEST, '', req_id),
        )

        # use request_handler that waits on STDIN so we can abort
        # it while it's running
        handler = run_handler(records, role=role,
                              request_handler=copy_stdin_to_stdout)

        rec = find_rec(handler, FCGI_END_REQUEST, req_id)
        assert rec and unpack_end_request(rec.content)

        for stream in FCGI_STDOUT, FCGI_STDERR:
            assert '' == read_stream(handler, stream, req_id)

    def test_request_multiplexing(self):
        req_id = next_req_id()
        req_id_2 = next_req_id()
        req_id_3 = next_req_id()
        role = FCGI_RESPONDER
        flags = 0
        records = (
            (FCGI_BEGIN_REQUEST, pack_begin_request(role, flags), req_id),
            (FCGI_PARAMS, pack_env(), req_id),
            (FCGI_BEGIN_REQUEST, pack_begin_request(role, flags), req_id_2),
            (FCGI_BEGIN_REQUEST, pack_begin_request(role, flags), req_id_3),
            (FCGI_PARAMS, pack_env(), req_id_3),
            (FCGI_PARAMS, pack_env(), req_id_2),
            (FCGI_PARAMS, '', req_id_2),
            (FCGI_PARAMS, '', req_id),
            (FCGI_ABORT_REQUEST, '', req_id_3),
        )

        handler = run_handler(records, role=role)

        assert not handler.requests
        assert handler.request_handler.call_count == 2
        assert handler.conn.close.called

        for r_id in req_id, req_id_2, req_id_3:
            rec = find_rec(handler, FCGI_END_REQUEST, r_id)
            assert rec and unpack_end_request(rec.content)

            for stream in FCGI_STDOUT, FCGI_STDERR:
                assert '' == read_stream(handler, stream, r_id)


# Helper functions

def copy_stdin_to_stdout(request):
    """
    Simple request handler
    """
    request.stdout.write(request.stdin.read())


def make_record(record_type, content='', request_id=FCGI_NULL_REQUEST_ID):
    return Record(record_type, content, request_id)


def iter_records(records, done=None):
    for rec in records:
        if isinstance(rec, tuple):
            rec = make_record(*rec)
        elif isinstance(rec, (int, float)):
            sleep(rec)
            continue
        elif isinstance(rec, event.Event):
            rec.set()
            continue
        yield rec
        sleep(0)


def run_handler(records, role=FCGI_RESPONDER, request_handler=None,
                capabilities=None, timeout=None):
    conn = mock.MagicMock()
    conn.__iter__.return_value = iter_records(records)

    if capabilities is None:
        capabilities = {
            FCGI_MAX_CONNS: '1',
            FCGI_MAX_REQS: '1',
            FCGI_MPXS_CONNS: '0',
        }

    if request_handler is None:
        request_handler = mock.MagicMock()

    handler = ConnectionHandler(conn, role, capabilities, request_handler)
    g = spawn(handler.run)
    g.join(timeout)

    return handler


def read_records(conn, req_id=None):
    return [args[0] for args, kw in conn.write_record.call_args_list
            if req_id is None or args[0].request_id == req_id]


def find_rec(handler, rec_type, req_id=FCGI_NULL_REQUEST_ID):
    records = read_records(handler.conn, req_id)
    for rec in records:
        if rec.type == rec_type:
            return rec
    assert False, 'No %s record found in %r' % (rec_type, records)


def read_stream(handler, rec_type, req_id):
        closed = False
        content = []

        for rec in read_records(handler.conn, req_id):
            if rec.type == rec_type:
                assert not closed, 'Stream is already closed'
                if rec.content:
                    content.append(rec.content)
                else:
                    closed = True

        assert closed, 'Stream was not closed'

        return ''.join(content)


next_req_id = count(1).next


if __name__ == '__main__':
    unittest.main()
