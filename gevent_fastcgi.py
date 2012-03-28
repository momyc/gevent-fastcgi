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

"""
FastCGI/WSGI server implemented using gevent library.
Supports connection multiplexing. Contains paste.server_runner entry point.
"""

import os
import sys
import logging
from tempfile import TemporaryFile
from struct import pack, unpack
from wsgiref.handlers import BaseCGIHandler

from gevent import spawn, socket
from gevent.server import StreamServer
from gevent.event import Event
from gevent.queue import Queue
from gevent.greenlet import LinkedExited

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO


__version__ = '0.1.3dev'

__all__ = [
    'run_server',
    'WSGIServer',
    'ClientConnection',
    'ProtocolError',
    'InputStream',
    'OutputStream',
    'pack_pairs',
    'unpack_pairs',
    ]

FCGI_VERSION = 1
FCGI_LISTENSOCK_FILENO = 0
FCGI_HEADER_LEN = 8
FCGI_BEGIN_REQUEST = 1
FCGI_ABORT_REQUEST = 2
FCGI_END_REQUEST = 3
FCGI_PARAMS = 4
FCGI_STDIN = 5
FCGI_STDOUT = 6
FCGI_STDERR = 7
FCGI_DATA = 8
FCGI_GET_VALUES = 9
FCGI_GET_VALUES_RESULT = 10
FCGI_UNKNOWN_TYPE = 11
FCGI_MAXTYPE = FCGI_UNKNOWN_TYPE
FCGI_NULL_REQUEST_ID = 0
FCGI_RECORD_HEADER_LEN = 8
FCGI_KEEP_CONN = 1
FCGI_RESPONDER = 1
FCGI_AUTHORIZER = 2
FCGI_FILTER = 3
FCGI_REQUEST_COMPLETE = 0
FCGI_CANT_MPX_CONN = 1
FCGI_OVERLOADED = 2
FCGI_UNKNOWN_ROLE = 3

__all__.extend(name for name in locals().keys() if name.startswith('FCGI_'))

FCGI_RECORD_TYPES = {
    FCGI_BEGIN_REQUEST: 'FCGI_BEGIN_REQUEST',
    FCGI_ABORT_REQUEST: 'FCGI_ABORT_REQUEST',
    FCGI_END_REQUEST: 'FCGI_END_REQUEST',
    FCGI_PARAMS: 'FCGI_PARAMS',
    FCGI_STDIN: 'FCGI_STDIN',
    FCGI_STDOUT: 'FCGI_STDOUT',
    FCGI_STDERR: 'FCGI_STDERR',
    FCGI_DATA: 'FCGI_DATA',
    FCGI_GET_VALUES: 'FCGI_GET_VALUES',
    FCGI_GET_VALUES_RESULT: 'FCGI_GET_VALUES_RESULT',
}

FCGI_ROLES = {FCGI_RESPONDER: 'RESPONDER', FCGI_AUTHORIZER: 'AUTHORIZER', FCGI_FILTER: 'FILTER'}

EXISTING_REQUEST_REC_TYPES = frozenset((FCGI_STDIN, FCGI_PARAMS, FCGI_ABORT_REQUEST))

HEADER_STRUCT = '!BBHHBx'
BEGIN_REQUEST_STRUCT = '!HB5x'
END_REQUEST_STRUCT = '!LB3x'
UNKNOWN_TYPE_STRUCT = '!B7x'

logger = logging.getLogger(__file__)

def pack_pairs(pairs):
    def _len(s):
        l = len(s)
        return pack(('!L', '!B')[l < 128], l)

    if isinstance(pairs, dict):
        pairs = pairs.iteritems()
    return (_len(name) + _len(value) + name + value for name, value in pairs)

def unpack_pairs(stream):

    def read_len():
        b = stream.read(1)
        if not b:
            return None
        l = ord(b)
        if l & 128:
            b += stream.read(3)
            if len(b) != 4:
                raise ProtocolError('Failed to read name length')
            l = unpack('!L', b)[0] & 0x7FFFFFFF
        return l

    def read_str(l):
        s = stream.read(l)
        if len(s) != l:
            raise ProtocolError('Failed to read %s bytes')
        return s

    if isinstance(stream, basestring):
        stream = StringIO(stream)

    while True:
        name_len = read_len()
        if name_len is None:
            return
        value_len = read_len()
        if value_len is None:
            raise ProtocolError('Failed to read value length')
        yield read_str(name_len), read_str(value_len)


class ProtocolError(Exception):
    pass


class InputStream(object):
    """
    FCGI_STDIN or FCGI_DATA stream.
    Uses temporary file to store received data after max_mem octets have been received.
    """

    _block = frozenset(('read', 'readline', 'readlines', 'fileno', 'close', 'next'))

    def __init__(self, max_mem=1024):
        self.max_mem = max_mem
        self.landed = False
        self.file = StringIO()
        self.len = 0
        self.complete = Event()

    def land(self):
        if not self.landed:
            pos = self.file.tell()
            tmp_file = TemporaryFile()
            tmp_file.write(self.file.getvalue())
            self.file = tmp_file
            self.file.seek(pos)
            self.landed = True
            logger.debug('Stream landed at %s', self.len)

    def feed(self, data):
        if not data: # EOF mark
            logger.debug('InputStream EOF mark received %r', data)
            self.file.seek(0)
            self.complete.set()
            return
        self.len += len(data)
        if not self.landed and self.len > self.max_mem:
            self.land()
        self.file.write(data)

    def __iter__(self):
        return self.file

    def __getattr__(self, attr):
        # Block until all data is received
        if attr in self._block:
            logger.debug('Waiting for InputStream to be received in full')
            self.complete.wait()
            self._flip_attrs()
            return self.__dict__[attr]
        raise AttributeError, attr

    def _flip_attrs(self):
        for attr in self._block:
            if hasattr(self.file, attr):
                setattr(self, attr, getattr(self.file, attr))


class OutputStream(object):
    """
    FCGI_STDOUT or FCGI_STDERR stream.
    """
    def __init__(self, conn, req_id, rec_type):
        self.conn = conn
        self.req_id = req_id
        self.rec_type = rec_type
        self.closed = False

    def write(self, data):
        if self.closed:
            logger.warn('Write to closed %s', self)
            return
        if self.rec_type == FCGI_STDERR:
            sys.stderr.write(data)
        self.conn.output(self.rec_type, data, self.req_id)

    def flush(self):
        pass

    def close(self):
        if not self.closed:
            self.conn.output(self.rec_type, '', self.req_id)
            self.closed = True

    def __str__(self):
        return '%s-%s' % (FCGI_RECORD_TYPES[self.rec_type], self.req_id)


class Request(object):
    """
    FastCGI request representation for FastCGI connection multiplexing feature.
    """
    def __init__(self, conn, role, id, flags):
        self.role = role
        self.id = id
        self.keep_conn = flags & FCGI_KEEP_CONN
        self.stdin = InputStream()
        self.stdout = OutputStream(conn, id, FCGI_STDOUT)
        self.stderr = OutputStream(conn, id, FCGI_STDERR)
        self.data = InputStream()
        self.params = {}
        self.greenlet = None


class _Connection(object):
    """
    Base class for FastCGI client and server connections.
    FastCGI wire protocol implementation.
    """

    def __init__(self, sock, *args, **kwargs):
        self.sock = sock

    def write_record(self, rec_type, content='', req_id=FCGI_NULL_REQUEST_ID):
        clen = len(content)
        plen = -clen & 7
        header = pack(HEADER_STRUCT, FCGI_VERSION, rec_type, req_id, clen, plen)
        map(self.sock.sendall, (header, content, '\x00' * plen))

    def read_bytes(self, num):
        chunks = []
        while num > 0:
            chunk = self.sock.recv(num)
            if not chunk:
                break
            num -= len(chunk)
            chunks.append(chunk)
        return ''.join(chunks)
            
    def read_record(self):
        try:
            header = self.read_bytes(FCGI_RECORD_HEADER_LEN)
            if not header:
                logger.debug('Peer closed connection')
                return None, None, None
            ver, rec_type, req_id, clen, plen = unpack(HEADER_STRUCT, header)
            if ver != FCGI_VERSION:
                raise ProtocolError('Unsopported FastCGI version %s', ver)
            content = self.read_bytes(clen)
            if plen:
                self.read_bytes(plen)
        except socket.error, ex:
            if ex.errno == 104:
                self.close()
                return None, None, None
            else:
                raise
        except:
            self.close()
            raise

        logger.debug('Received %s bytes as %s record type for request %s',
                len(content), FCGI_RECORD_TYPES.get(rec_type, 'Unknown %s' % rec_type), req_id)
        return rec_type, req_id, content

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None
            logger.debug('Connection closed')


class ServerConnection(_Connection):
    """
    FastCGI server connection.
    Each requests is handled by separate Greenlet.
    One Greenlet started to serialize output from multiple requests.
    """
    def __init__(self, sock, handler, max_conns, max_reqs, mpxs_conns):
        super(ServerConnection, self).__init__(sock)
        self.handler = handler
        self.max_conns = str(max_conns)
        self.max_reqs = str(max_reqs)
        self.mpxs_conns = str(int(bool(mpxs_conns)))
        self.output_queue = Queue()
        # self.output_handler = spawn_link(self.handle_output)
        self.output_handler = spawn(self.handle_output)
        self.output_handler.link() # raise LinkedException in connection Greenlet to terminate it

    def run(self):
        self.requests = requests = {}
        while True:
            try:
                rec_type, req_id, content = self.read_record()
            except LinkedExited:
                # output handler exited
                break
            if rec_type is None:
                # connection was closed by peer
                break

            if rec_type in EXISTING_REQUEST_REC_TYPES:
                req = requests.get(req_id)
                if not req:
                    raise ProtocolError('%s record for non-existing request %s' % (FCGI_RECORD_TYPES[rec_type], req_id))
                if rec_type == FCGI_STDIN:
                    req.stdin.feed(content)
                elif rec_type == FCGI_DATA:
                    req.data.feed(content)
                elif rec_type == FCGI_PARAMS:
                    if req.greenlet:
                        raise ProtocolError('Unexpected FCGI_PARAMS for request %s' % req_id)
                    if content:
                        req.params.update(unpack_pairs(content))
                    else:
                        logger.debug('Starting handler for request %s: %r', req_id, req.params)
                        req.greenlet = spawn(self.handle_request, req)
                elif rec_type == FCGI_ABORT_REQUEST:
                    logger.debug('Abort record received for %s', req_id)
                    req.complete = True
            elif rec_type == FCGI_BEGIN_REQUEST:
                role, flags = unpack(BEGIN_REQUEST_STRUCT, content)
                if role in FCGI_ROLES:
                    requests[req_id] = Request(self, role, req_id, flags)
                    logger.debug('New %s request %s with flags %04x', FCGI_ROLES[role], req_id, flags)
                else:
                    self.output(FCGI_END_REQUEST, pack(END_REQUEST_STRUCT, 0,  FCGI_UNKNOWN_ROLE), req_id)
                    logger.error('Unknown request role %s', role)
            elif rec_type == FCGI_GET_VALUES:
                self.output(FCGI_GET_VALUES_RESULT, ''.join(pack_pairs([
                    ('FCGI_MAX_CONNS', self.max_conns),
                    ('FCGI_MAX_REQS', self.max_reqs),
                    ('FCGI_MPXS_CONNS', self.mpxs_conns),
                    ])))
                self.output(FCGI_GET_VALUES_RESULT)
            else:
                logger.error('Unknown record type %s received', rec_type)
                self.output(FCGI_UNKNOWN_TYPE, pack('!B7x', rec_type))

        logger.debug('Finishing connection handler')
        self.close()
        
    def handle_request(self, req):
        try:
            self.handler(req)
        except:
            logger.exception('Request %s handler failed', req.id)
        req.stdout.close()
        req.stderr.close()
        self.output(FCGI_END_REQUEST, pack(END_REQUEST_STRUCT, 0, FCGI_REQUEST_COMPLETE), req.id)
        self.requests.pop(req.id)
        if not self.requests and not req.keep_conn:
            logger.debug('Last handler finished')
            self.output(None)

    def output(self, rec_type, content='', req_id=FCGI_NULL_REQUEST_ID):
        self.output_queue.put((rec_type, content, req_id))

    def handle_output(self):
        exit_requested = False
        requests = self.requests
        queue = self.output_queue
        write_record = self.write_record
        while requests or not exit_requested:
            rec_type, content, req_id = queue.get()
            if rec_type is None:
                logger.debug('Request handler wants to close connection')
                exit_requested = True
                continue
            logger.debug('Sending %s %s %s', FCGI_RECORD_TYPES[rec_type], len(content), req_id)
            length = len(content)
            if length <= 0xFFFF:
                write_record(rec_type, content, req_id)
            else:
                offset = 0
                data = memoryview(content)
                while offset < length:
                    write_record(rec_type, data[offset:offset+0xFFFF], req_id)
                    offset += 0xFFFF
        logger.debug('Output handler finished')


class ClientConnection(_Connection):
    """
    FastCGI client connection. Implemented mostly for testing purposes but can be used
    to write FastCGI client.
    """

    def __init__(self, addr, timeout=None):
        if isinstance(addr, basestring):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        elif isinstance(addr, tuple):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        else:
            raise ValueError('Address must be a tuple or a string not %s', type(addr))

        sock.connect(addr)
        super(ClientConnection, self).__init__(sock)

    def send_begin_request(self, req_id, role=FCGI_RESPONDER, flags=0):
        self.write_record(FCGI_BEGIN_REQUEST, pack(BEGIN_REQUEST_STRUCT, FCGI_RESPONDER, flags), req_id)

    def send_abort_request(self, req_id):
        self.write_record(FCGI_ABORT_REQUEST, req_id=req_id)

    def send_params(self, params='', req_id=1):
        if params:
            params = ''.join(pack_pairs(params))
        self.write_record(FCGI_PARAMS, params, req_id)

    def send_stdin(self, content='', req_id=1):
        self.write_record(FCGI_STDIN, content, req_id)

    def send_data(self, content='', req_id=1):
        self.write_record(FCGI_DATA, content, req_id)

    def send_get_values(self):
        self.write_record(FCGI_GET_VALUES)

    def unpack_end_request(self, data):
        return unpack(END_REQUEST_STRUCT, data)


class WSGIServer(StreamServer):

    def __init__(self, bind_address, app, max_conns=1024, max_reqs=1024 * 1024, **kwargs):
        """
        Up to max_conns Greenlets will be spawned to handle connections
        """
        if isinstance(bind_address, basestring):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(bind_address)
            sock.listen(max_conns)
            bind_address = sock

        super(WSGIServer, self).__init__(bind_address, self.handle_connection, spawn=max_conns, **kwargs)
        self.app = app
        self.max_conns = max_conns
        self.max_reqs = max_reqs

    def handle_connection(self, sock, addr):
        logger.debug('New connection from %s', addr)
        conn = ServerConnection(sock, self.handle_request, self.max_conns, self.max_reqs, True)
        conn.run()

    def handle_request(self, req):
        """
        FastCGI request handler will be run in separate Greenlet
        """
        try:
            BaseCGIHandler(req.stdin, req.stdout, req.stderr, req.params).run(self.app)
        except:
            logger.exception('Failed to handle request %s', req.id)


def run_server(app, conf, host='127.0.0.1', port=5000, path=None, **kwargs):
    addr = path or (host, int(port))
    if kwargs.pop('patch_thread', True):
        from gevent.monkey import patch_thread
        patch_thread()
    WSGIServer(addr, app, **kwargs).serve_forever()

