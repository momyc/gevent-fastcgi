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


try:
    memoryview
except NameError:
    # pre-2.7
    def memoryview(data):
        return data


__version__ = '0.1.4dev'

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


try:
    from _speedups import unpack_pairs
except ImportError:

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


class Record(object):

    __slots__ = ('type', 'content', 'request_id')

    def __init__(self, record_type, content='', request_id=FCGI_NULL_REQUEST_ID):
        self.type = record_type
        self.content = content
        self.request_id = request_id

    def __str__(self):
        return 'Record(%s, %s, %s)' % (FCGI_RECORD_TYPES.get(self.type, self.type), self.request_id, len(self.content))


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
    def __init__(self, conn, request_id, record_type):
        self.conn = conn
        self.request_id = request_id
        self.record_type = record_type
        self.closed = False

    def write(self, data):
        if self.closed:
            logger.warn('Write to closed %s', self)
            return
        if self.record_type == FCGI_STDERR:
            sys.stderr.write(data)
        self.conn.output(self.record_type, data, self.request_id)

    def flush(self):
        pass

    def close(self):
        if not self.closed:
            self.conn.output(self.record_type, '', self.request_id)
            self.closed = True

    def __str__(self):
        return 'OutputStream(%s, %s)' % (FCGI_RECORD_TYPES[self.record_type], self.request_id)


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

    def write_record(self, record):
        logger.debug('Writing %s', record)
        content_len = len(record.content)
        padding = -content_len & 7
        header = pack(HEADER_STRUCT, FCGI_VERSION, record.type, record.request_id, content_len, padding)
        self.sock.sendall(''.join((header, record.content, '\x00' * padding)))

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
                return None
            version, record_type, request_id, content_len, padding = unpack(HEADER_STRUCT, header)
            if version != FCGI_VERSION:
                raise ProtocolError('Unsopported FastCGI version %s', version)
            content = self.read_bytes(content_len)
            if padding:
                self.read_bytes(padding)
            
            record = Record(record_type, content, request_id)
            logger.debug('Received %s', record)
            return record
        except socket.error, ex:
            logger.exception('Failed to read record from peer')
            self.close()
            return None

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

    def run(self):
        self.requests = requests = {}
        output_handler = spawn(self.handle_output)

        while True:
            record = self.read_record()
            if record is None:
                # connection can be closed by either remote peer or by output_handler
                if not output_handler.ready():
                    self.output(None) # ask output handler to exit once all is sent out
                    output_handler.join()
                break

            if record.type in EXISTING_REQUEST_REC_TYPES:
                request = requests.get(record.request_id)
                if not request:
                    raise ProtocolError('%s for non-existing request' % record)
                if record.type == FCGI_STDIN:
                    request.stdin.feed(record.content)
                elif record.type == FCGI_DATA:
                    request.data.feed(record.content)
                elif record.type == FCGI_PARAMS:
                    if request.greenlet:
                        raise ProtocolError('Unexpected FCGI_PARAMS for request %s' % request.id)
                    if record.content:
                        request.params.update(unpack_pairs(record.content))
                    else:
                        logger.debug('Starting handler for request %s: %r', request.id, request.params)
                        request.greenlet = spawn(self.handle_request, request)
                elif record.type == FCGI_ABORT_REQUEST:
                    if request.greenlet:
                        request.greenlet.kill()
                        request.greenlet = None
                    request.complete = True
                    logger.debug('Aborted request %s', record.rerequest_id)
            elif record.type == FCGI_BEGIN_REQUEST:
                role, flags = unpack(BEGIN_REQUEST_STRUCT, record.content)
                if role in FCGI_ROLES:
                    requests[record.request_id] = Request(self, role, record.request_id, flags)
                    logger.debug('New %s request %s with flags %04x', FCGI_ROLES[role], record.request_id, flags)
                else:
                    self.output(FCGI_END_REQUEST, pack(END_REQUEST_STRUCT, 0,  FCGI_UNKNOWN_ROLE), record.request_id)
                    logger.error('Unknown request role %s', role)
            elif record.type == FCGI_GET_VALUES:
                self.output(FCGI_GET_VALUES_RESULT, ''.join(pack_pairs([
                    ('FCGI_MAX_CONNS', self.max_conns),
                    ('FCGI_MAX_REQS', self.max_reqs),
                    ('FCGI_MPXS_CONNS', self.mpxs_conns),
                    ])))
                self.output(FCGI_GET_VALUES_RESULT)
            else:
                logger.error('%s: Unknown record type' % record)
                self.output(FCGI_UNKNOWN_TYPE, pack('!B7x', record.type))

        logger.debug('Finished connection handler')
        
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

    def output(self, record_type, content='', request_id=FCGI_NULL_REQUEST_ID):
        if record_type is None:
            self.output_queue.put(None)
        else:
            self.output_queue.put(Record(record_type, content, request_id))

    def handle_output(self):
        exit_requested = False
        requests = self.requests
        queue = self.output_queue
        write_record = self.write_record

        while requests or not exit_requested:
            record = queue.get()
            if record is None:
                logger.debug('Request handler wants to close connection')
                exit_requested = True
                continue
            logger.debug('Sending %s', record)
            length = len(record.content)
            if length <= 0xFFFF:
                write_record(record)
            else:
                offset = 0
                data = memoryview(record.content)
                while offset < length:
                    write_record(Record(record.type, data[offset:offset+0xFFFF], record.request_id))
                    offset += 0xFFFF
        self.close()
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

    def send_begin_request(self, request_id, role=FCGI_RESPONDER, flags=0):
        self.write_record(Record(FCGI_BEGIN_REQUEST, pack(BEGIN_REQUEST_STRUCT, FCGI_RESPONDER, flags), request_id))

    def send_abort_request(self, request_id):
        self.write_record(Record(FCGI_ABORT_REQUEST, request_id=request_id))

    def send_params(self, params='', request_id=1):
        if params:
            params = ''.join(pack_pairs(params))
        self.write_record(Record(FCGI_PARAMS, params, request_id))

    def send_stdin(self, content='', request_id=1):
        self.write_record(Record(FCGI_STDIN, content, request_id))

    def send_data(self, content='', request_id=1):
        self.write_record(Record(FCGI_DATA, content, request_id))

    def send_get_values(self):
        self.write_record(Record(FCGI_GET_VALUES))

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

