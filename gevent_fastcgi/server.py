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
from struct import pack, unpack

from gevent import socket, spawn
from gevent.queue import Queue
from gevent.server import StreamServer

from gevent_fastcgi.base import *


__all__ = ('run_server', 'WSGIServer')


logger = getLogger(__name__)


class Request(object):
    """
    FastCGI request representation for FastCGI connection multiplexing feature.
    """
    def __init__(self, conn, id, flags):
        self.id = id
        self.flags = flags
        self.environ = {}
        self.greenlet = None
        self.stdout = OutputStream(conn, id, FCGI_STDOUT)
        self.stderr = OutputStream(conn, id, FCGI_STDERR)


class ServerConnection(BaseConnection):
    """
    FastCGI server connection spawns output handler to serialize output
    """
    def __init__(self, sock):
        super(ServerConnection, self).__init__(sock)
        self._queue = Queue()
        self._handler = spawn(self._handle_output)

    def write_record(self, record):
        self._queue.put(record)
        
    def close(self):
        if not self._handler.ready():
            self._queue.put(None)
            self._handler.join()
        super(ServerConnection, self).close()

    def _handle_output(self):
        write_record = super(ServerConnection, self).write_record
        for record in self._queue:
            if record is None:
                super(ServerConnection, self).close()
                logger.debug('Output handler finished')
                break
            write_record(record)


class Application(object):

    def __init__(self, server, conn):
        self.server = server
        self.conn = conn
        self.requests = {}

    def reply(self, record_type, content='', request_id=FCGI_NULL_REQUEST_ID):
        self.conn.write_record(Record(record_type, content, request_id))

    def run_app(self, request):
        try:
            handler = BaseCGIHandler(request.stdin, request.stdout, request.stderr, request.environ)
            handler.run(self.server.app)
            request.stdout.close()
            request.stderr.close()
        finally:
            self.reply(FCGI_END_REQUEST, pack(END_REQUEST_STRUCT, 0, FCGI_REQUEST_COMPLETE), request.id)
            del self.requests[request.id]
            if request.flags & FCGI_KEEP_CONN == 0:
                self.conn.close()

    def fcgi_params(self, record, request):
        if record.content:
            request.environ.update(map(unpack_pair, record.content))
        else:
            self.run()

    def fcgi_begin_request(self, record):
        role, flags = unpack(BEGIN_REQUEST_STRUCT, record.content)
        if role == self.server.role:
            request = Request(self.conn, record.request_id, flags)
            if role == FCGI_RESPONDER:
                request.stdin = InputStream()
            elif role == FCGI_FILTER:
                request.stdin = InputStream()
                request.data = InputStream()
            self.requests[request.id] = request
            logger.debug('New request %s with flags %04x', request.id, flags)
        else:
            self.reply(FCGI_END_REQUEST, pack(END_REQUEST_STRUCT, 0,  FCGI_UNKNOWN_ROLE), record.request_id)
            logger.error('Unknown request role %s', role)

    def fcgi_params(self, record, request):
        if record.content:
            request.environ.update(unpack_pairs(record.content))
        else:
            request.greenlet = spawn(self.run_app, request)

    def fcgi_abort_request(self, record, request):
        if request.greenlet:
            request.greenlet.kill()
            request.greenlet = None
        self.reply(FCGI_END_REQUEST, pack(END_REQUEST_STRUCT, 0, FCGI_REQUEST_COMPLETE), request.id)
        del self.requests[request.id]

    def fcgi_get_values(self, record):
        self.reply(FCGI_GET_VALUES_RESULT, self.server.values)
        self.reply(FCGI_GET_VALUES_RESULT)

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
                self.reply(FCGI_UNKNOWN_TYPE, pack('!B7x', record.type))
                self.conn.close()
                break

        logger.debug('Finished connection handler')


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
        self.values = ''.join(pack_pairs([
            ('FCGI_MAX_CONNS', str(max_conns)),
            ('FCGI_MAX_REQS', str(max_reqs)),
            ('FCGI_MPXS_CONNS', '1'),]))

    def handle_connection(self, sock, addr):
        logger.debug('New connection from %s', addr)
        conn = ServerConnection(sock)
        handler = Application(self, conn)
        handler.run()


def run_server(app, conf, host='127.0.0.1', port=5000, path=None, **kwargs):
    addr = path or (host, int(port))
    if kwargs.pop('patch_thread', True):
        from gevent.monkey import patch_thread
        patch_thread()
    WSGIServer(addr, app, **kwargs).serve_forever()

