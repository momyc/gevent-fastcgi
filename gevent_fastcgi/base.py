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

from __future__ import with_statement
import os
import sys
import logging
from errno import EPIPE, ECONNRESET
from tempfile import TemporaryFile
import struct
from zope.interface import implements

try:
    from cStringIO import StringIO
except ImportError: # pragma: no cover
    from StringIO import StringIO

from gevent import socket
from gevent.event import Event

from gevent_fastcgi.interfaces import IRecord, IConnection
from gevent_fastcgi.utils import pack_pairs, unpack_pairs, PartialRead, BufferedReader


logger = logging.getLogger('gevent_fastcgi')

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

header_struct = struct.Struct('!BBHHBx')
begin_request_struct = struct.Struct('!HB5x')
end_request_struct = struct.Struct('!LB3x')
unknown_type_struct = struct.Struct('!B7x')

logger = logging.getLogger(__name__)


class Record(object):
    
    implements(IRecord)
    __slots__ = ('type', 'content', 'request_id')

    def __init__(self, type, content='', request_id=FCGI_NULL_REQUEST_ID):
        if type < 0 or type > 255:
            raise ValueError('Record type must be between 0 and 255')
        self.type = type
        self.content = content
        self.request_id = request_id

    def __str__(self):
        return '<Record %s, req id %s, %d bytes>' % (FCGI_RECORD_TYPES.get(self.type, self.type), self.request_id, len(self.content))

    def __eq__(self, other):
        return isinstance(other, Record) and (self.type == other.type) and (self.request_id == other.request_id) and (self.content == other.content)


class Connection(object):
    
    implements(IConnection)
    
    def __init__(self, sock, buffer_size=4096):
        self._sock = sock
        self.buffered_reader = BufferedReader(sock.recv, buffer_size)

    def write_record(self, record):
        sendall = self._sock.sendall
        content_len = len(record.content)
        if content_len <= 0xffff:
            header = header_struct.pack(FCGI_VERSION, record.type, record.request_id, content_len, 0)
            sendall(header + record.content)
        elif record.type in (FCGI_STDIN, FCGI_STDOUT, FCGI_STDERR, FCGI_DATA):
            sent = 0
            content = record.content
            while sent < content_len:
                chunk_len = min(0xfff8, content_len - sent)
                header = header_struct.pack(FCGI_VERSION, record.type, record.request_id, chunk_len, 0)
                sendall(header + content[sent:sent+chunk_len])
                sent += chunk_len
        else:
            msg = 'Record content length %s exceeds maximum of %d' % (content_len, 0xffff)
            logger.error(msg)
            raise ValueError(msg)
  
    def read_record(self):
        read_bytes = self.buffered_reader.read_bytes
        
        try:
            header = read_bytes(FCGI_RECORD_HEADER_LEN)
        except PartialRead, x:
            if x.partial_data: # pragma: no cover - for some reason these two lines claimed as not covered
                logger.exception('Partial header received: %s' % x)
                raise
            # No error here. Remote side closed connection after sending all records
            return None

        version, record_type, request_id, content_len, padding = header_struct.unpack_from(header)

        if content_len:
            content = read_bytes(content_len)
        else:
            content = ''
        
        if padding: # pragma: no cover
            read_bytes(padding)

        return Record(record_type, content, request_id)

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None

    def done_writing(self):
        self._sock.shutdown(socket.SHUT_WR)

    def __iter__(self):
        return iter(self.read_record, None)


class InputStream(object):
    """
    FCGI_STDIN or FCGI_DATA stream.
    Uses temporary file to store received data after max_mem bytes have been received.
    """

    _block = frozenset(('read', 'readline', 'readlines', 'fileno', 'close', 'next'))

    def __init__(self, max_mem=1024):
        self.max_mem = max_mem
        self.landed = False
        self.file = StringIO()
        self.len = 0
        self.complete = Event()

    def land(self):
        """
        Switch from using in-memory to disk-file storage
        """
        if not self.landed:
            tmp_file = TemporaryFile()
            tmp_file.write(self.file.getvalue())
            self.file = tmp_file
            self.file.seek(0, 2)
            self.landed = True

    def feed(self, data):
        if not data: # EOF mark
            self.file.seek(0)
            self.complete.set()
            return
        self.len += len(data)
        if not self.landed and self.len > self.max_mem:
            self.land()
        self.file.write(data)

    def __iter__(self): # pragma: no cover
        self.complete.wait()
        self.__iter__ = self.file.__iter__
        return self.__iter__

    def __getattr__(self, attr):
        # Block until all data is received
        if attr in self._block:
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
            raise socket.error(9, 'File is already closed')

        if not data:
            return

        if self.record_type == FCGI_STDERR:
            sys.stderr.write(data)

        self.conn.write_record(Record(self.record_type, data, self.request_id))

    def writelines(self, lines):
        map(self.write, lines)

    def flush(self):
        pass

    def close(self):
        if not self.closed:
            self.conn.write_record(Record(self.record_type, '', self.request_id))
            self.closed = True

    def __str__(self):
        return 'OutputStream(%s, %s)' % (FCGI_RECORD_TYPES[self.record_type], self.request_id)
