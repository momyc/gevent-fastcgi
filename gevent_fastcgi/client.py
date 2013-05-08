from collections import defaultdict
from functools import partial

from gevent import socket, spawn, Timeout
from gevent.event import AsyncResult

from gevent_fastcgi.base import (
    Record,
    Connection,
    Request,
    pack_pairs,
    unpack_pairs,
)
from gevent_fastcgi.const import (
    FCGI_BEGIN_REQUEST,
    FCGI_DATA,
    FCGI_END_REQUEST,
    FCGI_FILTER,
    FCGI_GET_VALUES,
    FCGI_GET_VALUES_RESULT,
    FCGI_NULL_REQUEST_ID,
    FCGI_PARAMS,
    FCGI_RESPONDER,
    FCGI_STDERR,
    FCGI_STDIN,
    FCGI_STDOUT,
    begin_request_struct,
    end_request_struct,
)


class Client(object):

    def __init__(self, buffer_size=4096):
        self._conn = None
        self.buffer_size = buffer_size
        self._waiters = defaultdict(AsyncResult)

    def connect(self, address):
        if self._conn:
            raise ValueError('Client is already connected')

        if isinstance(address, (str, tuple)):
            if isinstance(address, str):
                af = socket.AF_UNIX
            else:
                af = socket.AF_INET
            sock = socket.socket(af, socket.SOCK_STREAM)
            sock.connect(address)
        else:
            # assume it's already connected socket
            sock = address

        self._conn = Connection(sock, self.buffer_size)

    def get_values(self, names, timeout=None):
        self.send(
            Record(FCGI_GET_VALUES, pack_pairs(dict.fromkeys(names, ''))))
        record = self.receive()
        if record.type != FCGI_GET_VALUES_RESULT:
            raise ValueError(
                'Unexpected record type received %s' % record.type)
        return dict(unpack_pairs(record.content))

    def run_request(self, environ, request_id=1, role=FCGI_RESPONDER,
                    stdin=None, data=None, flags=0):
        """
        Send request and receive response.
        Return tuple (app_status, stdout, stderr)
        """
        map(self.send, (
            Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(role, flags),
                   request_id),
            Record(FCGI_PARAMS, pack_pairs(environ), request_id),
            Record(FCGI_PARAMS),
            ))

        self._send_stream(request_id, stdin, FCGI_STDIN)

        if role == FCGI_FILTER:
            self._send_stream(request_id, data, FCGI_DATA)

        return self._get_response(request_id)

    def send(self, record):
        if self._conn is None:
            raise ValueError('Not connected')
        self._conn.write_record(record)

    def receive(self, request_id=FCGI_NULL_REQUEST_ID, timeout=None):
        if self._conn is None:
            raise ValueError('Not connected')

        with Timeout(timeout, None):
            return self._waiters[request_id].get()

    def _send_stream(self, request_id, stream, stream_type):
        if stream is not None:
            map(self.send, (
                Record(stream_type, chunk, request_id) for chunk in
                iter(partial(stream.read, 65535), '')))
        self.send(Record(stream_type, '', request_id))

    def _receive(self):
        waiters = self._waiters

        for record in self._conn:
            key = record.request_id
            if key in waiters:
                waiters[key].set(record)
                del waiters[key]

        for waiter in waiters.values():
            waiter.switch(None)

        waiters.clear()

    def _get_response(self, request_id, timeout=None):
        return spawn(self._response_reader, request_id).join(timeout)

    def _response_reader(self, request_id):
        stdout = InputStream()
        stderr = InputStream()
        for record in iter(partial(self.receive, request_id), None):
            if record.type == FCGI_STDOUT:
                stdout.feed(record.content)
            elif record.type == FCGI_STDERR:
                stderr.feed(record.content)
            elif record.type == FCGI_END_REQUEST:
                app_status, proto_status = end_request_struct.unpack(
                    record.content)
                return app_status, stdout, stderr
