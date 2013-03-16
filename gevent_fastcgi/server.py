# Copyright (c) 2011-2013, Alexander Kulakov
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#    The above copyright notice and this permission notice shall be included in
#    all copies or substantial portions of the Software.
#
#    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#    THE SOFTWARE.

from __future__ import with_statement

import os
import logging

from gevent.monkey import patch_os; patch_os()
from gevent import spawn, socket
from gevent.server import StreamServer
from gevent.coros import Semaphore
from gevent.event import Event

# all names starting with FCGI_ defined there
from gevent_fastcgi.const import *
from gevent_fastcgi.base import Connection, Record, InputStream, Request, pack_pairs, unpack_pairs


logger = logging.getLogger(__name__)


EXISTING_REQUEST_REC_TYPES = frozenset((
    FCGI_STDIN,
    FCGI_DATA,
    FCGI_PARAMS,
    FCGI_ABORT_REQUEST,
    ))


class ServerConnection(Connection):

    def __init__(self, *args, **kw):
        super(ServerConnection, self).__init__(*args, **kw)
        self.lock = Semaphore(1)

    def write_record(self, record):
        # We must serialize access for possible multiple request greenlets 
        with self.lock:
            super(ServerConnection, self).write_record(record)


class ConnectionHandler(object):

    def __init__(self, conn, role, capabilities, request_handler):
        self.conn = conn
        self.role = role
        self.capabilities = capabilities
        self.request_handler = request_handler
        self.requests = {}
        self.keep_open = None
        self.closing = False

    def send_record(self, record_type, content='', request_id=FCGI_NULL_REQUEST_ID):
        self.conn.write_record(Record(record_type, content, request_id))

    def _handle_request(self, request):
        try:
            self.request_handler(request)
            request.stdout.close()
            request.stderr.close()
        finally:
            self.send_record(FCGI_END_REQUEST, end_request_struct.pack(1, FCGI_REQUEST_COMPLETE), request.id)
            del self.requests[request.id]
            self.event.set()

    def fcgi_begin_request(self, record):
        role, flags = begin_request_struct.unpack(record.content)
        if role != self.role:
            self.send_record(FCGI_END_REQUEST, end_request_struct.pack(0,  FCGI_UNKNOWN_ROLE), record.request_id)
            logger.error('Request role (%s) does not match server role (%s)', role, self.role)
            self.event.set()
        else:
            # Should we check this for every request instead?
            if self.keep_open is None:
                self.keep_open = bool(FCGI_KEEP_CONN & flags)
            request = Request(self.conn, record.request_id, role)
            if role == FCGI_FILTER:
                request.data = InputStream()
            self.requests[request.id] = request

    def fcgi_params(self, record, request):
        if record.content:
            request.environ_list.append(record.content)
        else:
            request.environ.update(unpack_pairs(''.join(request.environ_list)))
            del request.environ_list
            if request.role == FCGI_AUTHORIZER:
                request.greenlet = spawn(self._handle_request, request)

    def fcgi_abort_request(self, record, request):
        greenlet = request.greenlet
        if not (greenlet is None or greenlet.ready()):
            request.greenlet.kill()
        if request.id in self.requests:
            del self.requests[request.id]
            self.event.set()
        logger.warn('Request %s aborted' % request.id)

    def fcgi_get_values(self, record):
        pairs = ((name, self.capabilities.get(name)) for name, _ in unpack_pairs(record.content))
        content = pack_pairs((name, str(value)) for name, value in pairs if value)
        self.send_record(FCGI_GET_VALUES_RESULT, content)
        self.event.set()

    def run(self): # pragma: no cover
        self.event = Event()
        reader = spawn(self._reader)
        while 1:
            self.event.wait()
            if self.requests or (self.keep_open and not reader.ready()):
                self.event.clear()
            else:
                break
        logger.debug('Closing connection')
        self.conn.close()

    def _reader(self):
        for record in self.conn:
            if record.type in EXISTING_REQUEST_REC_TYPES:
                request = self.requests.get(record.request_id)
                if not request:
                    logger.error('%s for non-existent request' % record)
                elif record.type == FCGI_STDIN: # pragma: no cover
                    request.stdin.feed(record.content)
                    if record.content == '' and request.role == FCGI_RESPONDER:
                        request.greenlet = spawn(self._handle_request, request)
                elif record.type == FCGI_DATA: # pragma: no cover
                    request.data.feed(record.content)
                    if record.content == '' and request.role == FCGI_FILTER:
                        request.greenlet = spawn(self._handle_request, request)
                elif record.type == FCGI_PARAMS: # pragma: no cover
                    self.fcgi_params(record, request)
                elif record.type == FCGI_ABORT_REQUEST: # pragma: no cover
                    self.fcgi_abort_request(record, request)
            elif record.type == FCGI_BEGIN_REQUEST:
                self.fcgi_begin_request(record)
            elif record.type == FCGI_GET_VALUES:
                self.fcgi_get_values(record)
            else:
                logger.error('%s: Unknown record type' % record)
                self.send_record(FCGI_UNKNOWN_TYPE, unknown_type_struct.pack(record.type))

        self.event.set() # pragma: no cover


class FastCGIServer(StreamServer):

    def __init__(self, bind_address, request_handler, role=FCGI_RESPONDER, num_workers=1, buffer_size=1024, max_conns=1024, **kwargs):
        """
        Up to max_conns Greenlets will be spawned to handle connections
        """
        if isinstance(bind_address, basestring):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(bind_address)
            self._socket_file = bind_address
            sock.listen(max_conns)
            bind_address = sock

        super(FastCGIServer, self).__init__(bind_address, self.handle_connection, spawn=max_conns, **kwargs)

        if role not in (FCGI_RESPONDER, FCGI_FILTER, FCGI_AUTHORIZER):
            raise ValueError('Illegal FastCGI role %s' % role)

        self.role = role
        self.request_handler = request_handler
        self.buffer_size = buffer_size
        self.capabilities = dict(
                FCGI_MAX_CONNS=str(max_conns),
                FCGI_MAX_REQS=str(max_conns * 1024),
                FCGI_MPXS_CONNS='1',
                )

        assert int(num_workers) >= 1, 'num_workers must be greate than zero'
        self.num_workers = int(num_workers)
        self.workers = []

    def start(self):
        super(FastCGIServer, self).start()
        if self.num_workers > 1:
            for _ in range(self.num_workers):
                pid = os.fork()
                if pid:
                    self.workers.append(pid)
                else: # pragma: no cover
                    # master process should take care of it
                    try:
                        self.serve_forever()
                    finally:
                        sys.exit()

    def stop(self, *args, **kw):
        super(FastCGIServer, self).stop(*args, **kw)
        self._cleanup()

    def handle_connection(self, sock, addr):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            sock.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
        conn = ServerConnection(sock, self.buffer_size)
        handler = ConnectionHandler(conn, self.role, self.capabilities, self.request_handler)
        handler.run()


    def _cleanup(self):
        for pid in self.workers:
            try:
                os.kill(pid, 15)
                os.waitpid(pid, 0)
            except OSError: # pragma: no cover
                logging.exception('Failed to kill child process %s' % pid)
                pass
        self.workers = []

        if hasattr(self, '_socket_file'):
            try:
                os.unlink(self._socket_file)
            finally:
                del self._socket_file
