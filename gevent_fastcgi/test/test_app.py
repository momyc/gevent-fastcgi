import unittest
from itertools import count
from random import randint
from decorator import decorator

from gevent_fastcgi.base import *
from gevent_fastcgi.server import WSGIServer, ConnectionHandler


@decorator
def coroutine(func, *args, **kw):
    result = func(*args, **kw)
    result.next()
    return result


class MockServer:
    role = FCGI_RESPONDER

    @staticmethod
    def capability(name):
        return {
            FCGI_MAX_CONNS: '1000',
            FCGI_MAX_REQS: '1000',
            FCGI_MPXS_CONNS: '1',
            }.get(name)

    @staticmethod
    def app(environ, start_response):
        start_response('200 OK', [('Content-type', 'text/plain')])
        yield 'Hi there!'


class MockConnection:

    def __init__(self, records):
        self.input = records
        self.output = []

    def __iter__(self):
        return (isinstance(record, Record) and record or Record(*record) for record in self.input)

    def write_record(self, record):
        self.output.append(record)

    def close(self):
        pass

    def shutdown(self, how):
        pass

    def flush(self):
        pass


class Request(object):

    def __(self, requestid, environ=None):
        self.request_id = request_id
        self.environ = dict(environ)
        self.records = [
            (FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), request_id),
            ]
        if environ:
            self.records.append((FCGI_PARAMS, ''.join(pack_pairs(self._environ)), request_id))
        self.records += [
            (FCGI_PARAMS, '', request_id),
            (FCGI_STDIN, '', request_id),
            ]

    def response_reader(self, response):
        closed = {FCGI_STDOUT: False, FCGI_STDERR: False}
        ended = False
        for record in response:
            assert not ended
            assert record.request_id == self.request_id
            if record.type in (FCGI_STDOUT, FCGI_STDERR):
                assert not closed[record.type]
                if not record.content:
                    closed[record.type] = True
            elif record.type == FCGI_END_REQUEST:
                assert all(closed.values())
                ended = True
            else:
                raise ValueError('Unexpected record in response %s', record)
        assert ended


class RequestMultiplexer:

    def __init__(self, num_requests, max_active=500):
        self.num_requests = num_requests
        self.max_active = max_active
        self.demux = self._response_reader()

    def __iter__(self):
        max_index = self.max_active - 1
        next_request_id = count(1).next
        requests_left = self.num_requests
        requests = []

        while requests or requests_left:
            index = randint(0, max_index)
            try:
                request = requests[index]
            except IndexError:
                if requests_left:
                    requests.append(Request(next_request_id()))
                    requests_left -= 1
                else:
                    max_index = len(requests) - 1
            else:
                try:
                    yield request.next()
                except StopIteration:
                    del requests[index]


def fcgi_session(records):
    conn = MockConnection(records)
    handler = ConnectionHandler(MockServer, conn)
    handler.run()
    return conn.output

class AppTest(unittest.TestCase):

    def test_get_values(self):
        values_closed = False
        values = []

        for record in fcgi_session([(FCGI_GET_VALUES,)]):
            self.assertFalse(values_closed)
            if record.type == FCGI_GET_VALUES_RESULT:
                if record.content:
                    values.append(record.content)
                else:
                    values_closed = True
            else:
                self.Fail('Unexpected record in response %s', record)

        if values:
            print dict(unpack_pairs(''.join(values)))



