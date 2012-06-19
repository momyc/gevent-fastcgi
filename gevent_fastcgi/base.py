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
import sys
import logging
from tempfile import TemporaryFile
import struct

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from gevent import socket
from gevent.event import Event


__all__ = [
    'Record',
    'BaseConnection',
    'ProtocolError',
    'InputStream',
    'OutputStream',
    'pack_pairs',
    'unpack_pairs',
    'header_struct',
    'begin_request_struct',
    'end_request_struct',
    'unknown_type_struct',
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

FCGI_MAX_CONNS = 'FCGI_MAX_CONNS'
FCGI_MAX_REQS = 'FCGI_MAX_REQS'
FCGI_MPXS_CONNS = 'FCGI_MPXS_CONNS'

__all__.extend(name for name in locals().keys() if name.upper() == name)

header_struct = struct.Struct('!BBHHBx')
begin_request_struct = struct.Struct('!HB5x')
end_request_struct = struct.Struct('!LB3x')
unknown_type_struct = struct.Struct('!B7x')

logger = logging.getLogger(__name__)

try:
    from gevent_fastcgi.speedups import pack_pair, unpack_pairs
except ImportError:

    length_struct = struct.Struct('!L')

    def pack_len(s):
        l = len(s)
        if l < 128:
            return chr(l)
        elif l > 0x7fffffff:
            raise ValueError('Maximum name or value length is %d', 0x7fffffff)
        return length_struct.pack(l | 0x80000000)

    def pack_pair(name, value):
        return ''.join((pack_len(name), pack_len(value), name, value))

    def unpack_len(buf, pos):
        _len = ord(buf[pos])
        if _len & 128:
            _len = length_struct.unpack_from(buf, pos)[0] & 0x7fffffff
            pos += 4
        else:
            pos += 1
        return _len, pos

    def unpack_pairs(data):
        end = len(data)
        pos = 0
        while pos < end:
            try:
                name_len, pos = unpack_len(data, pos)
                value_len, pos = unpack_len(data, pos)
                name = data[pos:pos + name_len]
                pos += name_len
                value = data[pos:pos + value_len]
                pos += value_len
                yield name, value
            except (IndexError, struct.error):
                raise ProtocolError('Failed to unpack name/value pairs')

def pack_pairs(pairs):
    if isinstance(pairs, dict):
        pairs = pairs.iteritems()

    return ''.join(pack_pair(name, value) for name, value in pairs)


class ProtocolError(Exception):
    pass


class Record(object):
    __slots__ = ('type', 'content', 'request_id')

    def __init__(self, type, content='', request_id=FCGI_NULL_REQUEST_ID):
        self.type = type
        self.content = content
        self.request_id = request_id

    def __str__(self):
        return '<Record %s, req id %s, %d bytes>' % (FCGI_RECORD_TYPES.get(self.type, self.type), self.request_id, len(self.content))


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
        
        self.conn.write_record(Record(self.record_type, data, self.request_id))

    def flush(self):
        pass

    def close(self):
        if not self.closed:
            self.conn.write_record(Record(self.record_type, '', self.request_id))
            self.closed = True

    def __str__(self):
        return 'OutputStream(%s, %s)' % (FCGI_RECORD_TYPES[self.record_type], self.request_id)


class BaseConnection(object):
    """
    Base class for FastCGI client and server connections.
    FastCGI wire protocol implementation.
    """

    def __init__(self, sock, buffer_size=4096, *args, **kwargs):
        self._sock = sock
        self.reader = self.reader(buffer_size)
        self.reader.next()

    def write_record(self, record):
        sendall = self._sock.sendall
        content_len = len(record.content)
        padding = 0
        if content_len <= 0xffff:
            header = header_struct.pack(FCGI_VERSION, record.type, record.request_id, content_len, padding)
            sendall(header)
            if content_len:
                sendall(record.content)
                if padding:
                    sendall('\0' * padding)
        elif record.type in (FCGI_STDIN, FCGI_STDOUT, FCGI_STDERR, FCGI_DATA):
            sent = 0
            content = record.content
            while sent < content_len:
                chunk_len = min(0xffff, content_len)
                header = header_struct.pack(FCGI_VERSION, record.type, record.request_id, chunk_len, padding)
                sendall(header)
                sendall(content[sent:sent+chunk_len])
                if padding:
                    sendall('\0' * padding)
                sent += chunk_len
        else:
            raise ValueError('Content length %d exceeds maximum of %d', content_len, 0xffff)
  
    def read_record(self):
        read = self.reader.send
        try:
            header = read(FCGI_RECORD_HEADER_LEN)
            if not header:
                logger.debug('Peer closed connection')
                return None
            version, record_type, request_id, content_len, padding = header_struct.unpack(header)
            if version != FCGI_VERSION:
                raise ProtocolError('Unsopported FastCGI version %s', version)
            if content_len:
                content = read(content_len)
            else:
                content = ''
            if padding:
                read(padding)
            return Record(record_type, content, request_id)
        except socket.error, ex:
            logger.exception('Failed to read record from peer')
            self.close()
            return None

    def __iter__(self):
        return self

    def next(self):
        record = self.read_record()
        if record is None:
            raise StopIteration
        return record

    def close(self):
        if self._sock:
            self._sock.shutdown(socket.SHUT_RD | socket.SHUT_WR)
            self._sock.close()
            self._sock = None
            logger.debug('Connection closed')

    def reader(self, buf_size):
        recv = self._sock.recv
        buf = ''
        blen = 0
        chunks = []
        requested = (yield)
        while True:
            if blen >= requested:
                data, buf = buf[:requested], buf[requested:]
                blen -= requested
            else:
                while blen < requested:
                    if buf:
                        chunks.append(buf)
                    buf = recv(max(buf_size, requested - blen))
                    rlen = len(buf)
                    if not rlen:
                        break # EOF
                    blen += rlen
                blen -= requested
                if blen:
                    chunks.append(buf[:-blen])
                    buf = buf[-blen:]
                else:
                    chunks.append(buf)
                    buf = ''
                data = ''.join(chunks)
                chunks = []
            
            requested = yield data

