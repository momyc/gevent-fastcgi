# Copyright (c) 2011-2012, Alexander Kulakov
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

import os
import logging
from zope.interface import implements
from wsgiref.handlers import BaseCGIHandler

from gevent import socket, spawn, joinall
from gevent.server import StreamServer
from gevent.coros import RLock

from gevent_fastcgi.interfaces import IServer
from gevent_fastcgi.base import *


logger = logging.getLogger(__name__)


EXISTING_REQUEST_REC_TYPES = frozenset((
    FCGI_STDIN,
    FCGI_DATA,
    FCGI_PARAMS,
    FCGI_ABORT_REQUEST,
    ))


class Request(object):
    
    def __init__(self, conn, request_id):
        self.conn = conn
        self.id = request_id
        self.stdin = InputStream()
        self.stdout = OutputStream(conn, request_id, FCGI_STDOUT)
        self.stderr = OutputStream(conn, request_id, FCGI_STDERR)
        self.environ_list = []
        self.environ = {}
        self.greenlet = None

    def run(self, app):
        handler = BaseCGIHandler(self.stdin, self.stdout, self.stderr, self.environ)
        handler.run(app)


class ServerConnection(Connection):

    def __init__(self, *args, **kw):
        super(ServerConnection, self).__init__(*args, **kw)
        self.lock = RLock()

    def write_record(self, record):
        # We must serialize access for possible multiple request greenlets 
        with self.lock:
            super(ServerConnection, self).write_record(record)


class ConnectionHandler(object):

    def __init__(self, server, conn):
        self.server = server
        self.conn = conn
        self.requests = {}
        self.keep_conn = False

    def reply(self, record_type, content='', request_id=FCGI_NULL_REQUEST_ID):
        self.conn.write_record(Record(record_type, content, request_id))

    def run_app(self, request):
        try:
            request.run(self.server.app)
            request.stdout.close()
            request.stderr.close()
            self.reply(FCGI_END_REQUEST, end_request_struct.pack(0, FCGI_REQUEST_COMPLETE), request.id)
        finally:
            del self.requests[request.id]
            if not self.requests and not self.keep_conn:
                self.conn.close()

    def fcgi_begin_request(self, record):
        role, flags = begin_request_struct.unpack(record.content)
        if role != self.server.role:
            self.reply(FCGI_END_REQUEST, end_request_struct.pack(0,  FCGI_UNKNOWN_ROLE), record.request_id)
            logger.error('Request role is %s but server is configured with %s', role, self.server.role)
        else:
            self.keep_conn = bool(FCGI_KEEP_CONN & flags)
            request = Request(self.conn, record.request_id)
            if role == FCGI_FILTER:
                request.data = InputStream()
            self.requests[request.id] = request

    def fcgi_params(self, record, request):
        if record.content:
            request.environ_list.append(record.content)
        else:
            request.environ.update(unpack_pairs(''.join(request.environ_list)))
            request.greenlet = spawn(self.run_app, request)

    def fcgi_abort_request(self, record, request):
        if request.greenlet is not None:
            request.greenlet.kill()
        else:
            del self.requests[request.id]

    def fcgi_get_values(self, record):
        pairs = ((name, self.server.capability(name)) for name, _ in unpack_pairs(record.content))
        content = pack_pairs((name, str(value)) for name, value in pairs if value)
        self.reply(FCGI_GET_VALUES_RESULT, content)

    def run(self):
        """Main connection loop
        """
        requests = self.requests

        for record in iter(self.conn.read_record, None):
            if record.type in EXISTING_REQUEST_REC_TYPES:
                request = requests.get(record.request_id)
                if not request:
                    logger.error('Non-existent request in %s. Closing connection!' % record)
                    self.conn.close()
                    break
                if record.type == FCGI_STDIN:
                    request.stdin.feed(record.content)
                elif record.type == FCGI_DATA:
                    request.data.feed(record.content)
                elif record.type == FCGI_PARAMS:
                    self.fcgi_params(record, request)
                elif record.type == FCGI_ABORT_REQUEST:
                    logger.warn('Request abortion requested by server')
                    self.fcgi_abort_request(record, request)
            elif record.type == FCGI_BEGIN_REQUEST:
                self.fcgi_begin_request(record)
            elif record.type == FCGI_GET_VALUES:
                self.fcgi_get_values(record)
            else:
                logger.error('%s: Unknown record type' % record)
                self.reply(FCGI_UNKNOWN_TYPE, unknown_type_struct.pack(record.type))
                self.conn.close()
                break

        wait_list = [request.greenlet for request in requests.values() if request.greenlet is not None]
        if wait_list:
            joinall(wait_list)


class WSGIServer(StreamServer):

    implements(IServer)

    def __init__(self, bind_address, app, max_conns=1024, max_reqs=1024 * 1024, **kwargs):
        """
        Up to max_conns Greenlets will be spawned to handle connections
        """
        if isinstance(bind_address, basestring):
            self._socket_file = bind_address
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(bind_address)
            sock.listen(max_conns)
            bind_address = sock

        self.buffer_size = int(kwargs.pop('buffer_size', 1024))
        self.fork = int(kwargs.pop('num_workers', 1))
        if self.fork <= 0:
            raise ValueError('num_workers must be equal or greate than 1')
        role = kwargs.pop('role', FCGI_RESPONDER)

        super(WSGIServer, self).__init__(bind_address, self.handle_connection, spawn=max_conns, **kwargs)

        if isinstance(role, basestring):
            role = role.lower().strip()
            if role == 'responder':
                role = FCGI_RESPONDER
            elif role == 'filter':
                role = FCGI_FILTER
            elif role == 'authorizer':
                role = FCGI_AUTHORIZER
            else:
                raise ValueError('Unknown FastCGI role %s', role)
        else:
            role = int(role)
            if role not in (FCGI_RESPONDER, FCGI_FILTER, FCGI_AUTHORIZER):
                raise ValueError('Unknown FastCGI role %s', role)
        
        self.role = role
        self.app = app
        self.capabilities = dict(
                FCGI_MAX_CONNS=str(max_conns),
                FCGI_MAX_REQS=str(max_reqs),
                FCGI_MPXS_CONNS='1',
                )
        self.workers = []

    def start(self):
        super(WSGIServer, self).start()
        if self.fork > 1:
            from gevent.monkey import patch_os
            patch_os()

            for i in range(self.fork):
                pid = os.fork()
                if pid < 0: # pragma: no cover
                    sys.exit('Failed to fork worker %s', i)
                if pid == 0:
                    return # pragma: no cover
                self.workers.append(pid)

    def stop(self):
        super(WSGIServer, self).stop()
        self._cleanup()
            
    def handle_connection(self, sock, addr):
        sock.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
        conn = ServerConnection(sock, self.buffer_size)
        handler = ConnectionHandler(self, conn)
        handler.run()

    def capability(self, name):
        return self.capabilities.get(name, '')

    def _cleanup(self):
        from signal import SIGHUP

        for pid in self.workers:
            os.kill(pid, SIGHUP)
            os.waitpid(pid, 0)
        self.workers = []

        if hasattr(self, '_socket_file'):
            os.unlink(self._socket_file)
            del self._socket_file
