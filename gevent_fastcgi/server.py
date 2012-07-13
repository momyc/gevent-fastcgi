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


from wsgiref.handlers import BaseCGIHandler
from logging import getLogger

from gevent import socket, spawn, joinall
from gevent.event import Event
from gevent.server import StreamServer

from gevent_fastcgi.base import *


__all__ = ('run_server', 'WSGIServer')


logger = getLogger(__name__)


FCGI_ROLES = {FCGI_RESPONDER: 'RESPONDER', FCGI_AUTHORIZER: 'AUTHORIZER', FCGI_FILTER: 'FILTER'}

EXISTING_REQUEST_REC_TYPES = frozenset((
    FCGI_STDIN,
    FCGI_PARAMS,
    FCGI_ABORT_REQUEST,
    ))

MANDATORY_WSGI_ENVIRON_VARS = frozenset((
    'REQUEST_METHOD',
    'SCRIPT_NAME',
    'PATH_INFO',
    'QUERY_STRING',
    'CONTENT_TYPE',
    'CONTENT_LENGTH',
    'SERVER_NAME',
    'SERVER_PORT',
    'SERVER_PROTOCOL',
    ))


class Response(object):

    def __init__(self, status, headers):
        self.status = status
        self.headers = [(name.lower(), value) for name, value in headers]
        self.headers_sent = False


class Request(object):
    """
    FastCGI request representation for FastCGI connection multiplexing feature.
    """
    def __init__(self, conn, id, role, flags):
        self.id = id
        self.role = role
        self.flags = flags
        self.environ = []
        self.stdout = OutputStream(conn, id, FCGI_STDOUT)
        self.stderr = OutputStream(conn, id, FCGI_STDERR)
        self.response = None

    def run_app(self, application):
        environ = self._make_environ()
        response = application(environ, self._start_response)
        
        write = self.stdout.write
        
        # do nothing until first non-empty chunk
        for chunk in response:
            if chunk:
                self._send_headers()
                write(chunk)
                break
        
        map(write, response)

        if not self.response.headers_sent:
            self._send_headers()

        self.stdout.close()
        self.stderr.close()

        close = getattr(response, 'close', None)
        if close is not None:
            close()

    def _make_environ(self):
        env = self.environ
        
        for name in MANDATORY_WSGI_ENVIRON_VARS.difference(env):
            env[name] = ''

        env['wsgi.version'] = (1, 0)
        env['wsgi.input'] = self.stdin
        env['wsgi.errors'] = self.stderr
        env['wsgi.multithread'] = True # the same application may be simulteneously invoked in the same process
        env['wsgi.multiprocess'] = False
        env['wsgi.run_once'] = False

        https = env.get('HTTPS','').lower()
        if https in ('yes', 'on', '1'):
            env['wsgi.url_scheme'] = 'https'
        else:
            env['wsgi.url_scheme'] = 'http'

        return env

    def _start_response(self, status, headers, exc_info=None):
        if exc_info is not None:
            try:
                if self.status:
                    raise exc_info[1].with_traceback(exc_info[2])
            finally:
                exc_info = None

        assert self.response is None, 'start_response called more than once'

        self.response = Response(status, headers)

        return self._write_from_app

    def _send_headers(self):
        data = ['Status: %s' % self.response.status]
        data.extend('%s: %s' % hdr for hdr in self.response.headers)
        data.append('\r\n')
        self.stdout.write('\r\n'.join(data))
        self.response.headers_sent = True

    def _write_from_app(self, chunk):
        if not chunk:
            return
        if not self.response.headers_sent:
            self._send_headers()
        self.stdout.write(chunk)


class ServerConnection(Connection):

    def __init__(self, *args, **kw):
        super(ServerConnection, self).__init__(*args, **kw)
        self.busy = False
        self.ready = Event()

    def __enter__(self):
        while self.busy:
            self.ready.wait()
        self.busy = True
        self.ready.clear()

    def __exit__(self, type, value, tb):
        self.busy = False
        self.ready.set()

    def write_record(self, record):
        with self:
            super(ServerConnection, self).write_record(record)

    def close(self):
        with self:
            super(ServerConnection, self).close()


class ConnectionHandler(object):

    def __init__(self, server, conn):
        self.server = server
        self.conn = conn
        self.requests = {}

    def reply(self, record_type, content='', request_id=FCGI_NULL_REQUEST_ID):
        self.conn.write_record(Record(record_type, content, request_id))

    def run_app(self, request):
        try:
            #handler = BaseCGIHandler(request.stdin, request.stdout, request.stderr, request.environ)
            #handler.run(self.server.app)
            #request.stdout.close()
            #request.stderr.close()
            request.run_app(self.server.app)
        finally:
            self.reply(FCGI_END_REQUEST, end_request_struct.pack(0, FCGI_REQUEST_COMPLETE), request.id)
            del self.requests[request.id]
            if not self.requests and (request.flags & FCGI_KEEP_CONN == 0):
                self.conn.close()

    def fcgi_begin_request(self, record):
        role, flags = begin_request_struct.unpack(record.content)
        if role == self.server.role:
            request = Request(self.conn, record.request_id, role, flags)
            if role == FCGI_RESPONDER:
                request.stdin = InputStream()
            elif role == FCGI_FILTER:
                request.stdin = InputStream()
                request.data = InputStream()
            self.requests[request.id] = request
        else:
            self.reply(FCGI_END_REQUEST, end_request_struct.pack(0,  FCGI_UNKNOWN_ROLE), record.request_id)
            logger.error('Unknown request role %s', role)

    def fcgi_params(self, record, request):
        if record.content:
            request.environ.append(record.content)
        else:
            request.environ = dict(unpack_pairs(''.join(request.environ)))
            request.greenlet = spawn(self.run_app, request)

    def fcgi_abort_request(self, record, request):
        if request.greenlet:
            request.greenlet.kill()
            request.greenlet = None
        self.reply(FCGI_END_REQUEST, end_request_struct.pack(0, FCGI_REQUEST_COMPLETE), request.id)
        del self.requests[request.id]

    def fcgi_get_values(self, record):
        pairs = ((name, self.server.capability(name)) for name, _ in unpack_pairs(record.content))
        content = pack_pairs((name, str(value)) for name, value in pairs if value)
        self.reply(FCGI_GET_VALUES_RESULT, content)

    def run(self):
        """Main connection loop
        """
        requests = self.requests

        for record in self.conn:
            if record.type in EXISTING_REQUEST_REC_TYPES:
                request = requests.get(record.request_id)
                if not request:
                    raise ProtocolError('%s for non-existing request' % record)
                if record.type == FCGI_STDIN:
                    request.stdin.feed(record.content)
                elif record.type == FCGI_DATA:
                    request.data.feed(record.content)
                elif record.type == FCGI_PARAMS:
                    self.fcgi_params(record, request)
                elif record.type == FCGI_ABORT_REQUEST:
                    self.fcgi_abort_request(request)
            elif record.type == FCGI_BEGIN_REQUEST:
                self.fcgi_begin_request(record)
            elif record.type == FCGI_GET_VALUES:
                self.fcgi_get_values(record)
            else:
                logger.error('%s: Unknown record type' % record)
                self.reply(FCGI_UNKNOWN_TYPE, unknown_type_struct.pack(record.type))
                self.conn.close()
                break

        joinall([request.greenlet for request in requests.values()])


class WSGIServer(StreamServer):

    def __init__(self, bind_address, app, max_conns=1024, max_reqs=1024 * 1024, multiplex=True, **kwargs):
        """
        Up to max_conns Greenlets will be spawned to handle connections
        """
        if isinstance(bind_address, basestring):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(bind_address)
            sock.listen(max_conns)
            bind_address = sock

        self.buffer_size = int(kwargs.pop('buffer_size', 1024))

        super(WSGIServer, self).__init__(bind_address, self.handle_connection, spawn=max_conns, **kwargs)

        if 'role' in kwargs:
            role = kwargs['role']
            if isinstance(role, basestring):
                role = role.lower().trim()
                if role == 'responder':
                    role = FCGI_RESPONDER
                elif role == 'filter':
                    role = FCGI_FILTER
                elif role == 'authorizer':
                    role = FCGI_AUTHORIZER
                else:
                    raise ValueError('Unknown FastCGI role %s', role)
        else:
            role = FCGI_RESPONDER
        
        self.role = role
        self.app = app
        self.capabilities = dict(
                FCGI_MAX_CONNS=max_conns,
                FCGI_MAX_REQS=max_reqs,
                FCGO_MPXS_CONNS=1,
                )

    def handle_connection(self, sock, addr):
        conn = Connection(sock, self.buffer_size)
        handler = ConnectionHandler(self, conn)
        handler.run()

    def capability(self, name):
        return self.capabilities.get(name)


def run_server(app, conf, host='127.0.0.1', port=5000, path=None, **kwargs):
    addr = path or (host, int(port))
    if kwargs.pop('patch_thread', True):
        from gevent.monkey import patch_thread
        patch_thread()
    WSGIServer(addr, app, **kwargs).serve_forever()

