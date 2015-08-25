# Copyright (c) 2011-2013, Alexander Kulakov
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from __future__ import with_statement

import logging
from collections import namedtuple
from tempfile import SpooledTemporaryFile

from zope.interface import implements
from gevent import socket
from gevent.event import Event

from .interfaces import IConnection
from .const import (
    FCGI_VERSION,
    FCGI_STDIN,
    FCGI_STDOUT,
    FCGI_STDERR,
    FCGI_DATA,
    FCGI_NULL_REQUEST_ID,
    FCGI_RECORD_HEADER_LEN,
    FCGI_RECORD_TYPES,
    FCGI_MAX_CONTENT_LEN,
)
from .utils import pack_header, unpack_header


__all__ = (
    'PartialRead',
    'BufferedReader',
    'Record',
    'Connection',
    'InputStream',
    'StdoutStream',
    'StderrStream',
)

logger = logging.getLogger(__name__)


class PartialRead(Exception):
    """ Raised by buffered_reader when it fails to read requested length
    of data
    """
    def __init__(self, requested_size, partial_data):
        super(PartialRead, self).__init__(
            'Expected {0} but received {1} bytes only'.format(
                requested_size, len(partial_data)))
        self.requested_size = requested_size
        self.partial_data = partial_data


class BufferedReader(object):
    """ Allows to receive data in large chunks
    """
    def __init__(self, read_callable, buffer_size):
        self._reader = self._reader_generator(read_callable, buffer_size)
        self._reader.next()  # advance generator to first yield statement

    def read_bytes(self, max_len):
        return self._reader.send(max_len)

    @staticmethod
    def _reader_generator(read, buf_size):
        buf = ''
        blen = 0
        chunks = []
        size = (yield)

        while True:
            if blen >= size:
                data, buf = buf[:size], buf[size:]
                blen -= size
            else:
                while blen < size:
                    chunks.append(buf)
                    buf = read(
                        (size - blen + buf_size - 1) // buf_size * buf_size)
                    if not buf:
                        raise PartialRead(size, ''.join(chunks))
                    blen += len(buf)

                blen -= size

                if blen:
                    chunks.append(buf[:-blen])
                    buf = buf[-blen:]
                else:
                    chunks.append(buf)
                    buf = ''

                data = ''.join(chunks)
                chunks = []

            size = (yield data)


class Record(namedtuple('Record', ('type', 'content', 'request_id'))):

    def __str__(self):
        return '<Record {0}, req id {1}, {2} bytes>'.format(
            FCGI_RECORD_TYPES.get(self.type, self.type),
            self.request_id,
            len(self.content))


class Connection(object):

    implements(IConnection)

    def __init__(self, sock, buffer_size=4096):
        self._sock = sock
        self.buffered_reader = BufferedReader(sock.recv, buffer_size)

    def write_record(self, record):
        send = self._sock.send
        content_len = len(record.content)
        if content_len > FCGI_MAX_CONTENT_LEN:
            raise ValueError('Record content length exceeds {0}'.format(
                FCGI_MAX_CONTENT_LEN))

        header = pack_header(
            FCGI_VERSION, record.type, record.request_id, content_len, 0)

        for buf, length in (
            (header, FCGI_RECORD_HEADER_LEN),
            (record.content, content_len),
        ):
            sent = 0
            while sent < length:
                sent += send(buffer(buf, sent))

    def read_record(self):
        read_bytes = self.buffered_reader.read_bytes

        try:
            header = read_bytes(FCGI_RECORD_HEADER_LEN)
        except PartialRead, x:
            if x.partial_data:
                logger.exception('Partial header received: {0}'.format(x))
                raise
            # Remote side closed connection after sending all records
            logger.debug('Connection closed by peer')
            return None

        version, record_type, request_id, content_len, padding = (
            unpack_header(header))

        if content_len:
            content = read_bytes(content_len)
        else:
            content = ''

        if padding:  # pragma: no cover
            read_bytes(padding)

        return Record(record_type, content, request_id)

    def __iter__(self):
        return iter(self.read_record, None)

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None

    def done_writing(self):
        self._sock.shutdown(socket.SHUT_WR)


class InputStream(object):
    """
    FCGI_STDIN or FCGI_DATA stream.
    Uses temporary file to store received data once max_mem bytes
    have been received.
    """
    def __init__(self, max_mem=1024):
        self._file = SpooledTemporaryFile(max_mem)
        self._eof_received = Event()

    def feed(self, data):
        if self._eof_received.is_set():
            raise IOError('Feeding file beyond EOF mark')
        if not data:  # EOF mark
            self._file.seek(0)
            self._eof_received.set()
        else:
            self._file.write(data)

    def __iter__(self):
        self._eof_received.wait()
        return iter(self._file)

    def read(self, size=-1):
        self._eof_received.wait()
        return self._file.read(size)

    def readline(self, size=-1):
        self._eof_received.wait()
        return self._file.readline(size)

    def readlines(self, sizehint=0):
        self._eof_received.wait()
        return self._file.readlines(sizehint)

    @property
    def eof_received(self):
        return self._eof_received.is_set()


class OutputStream(object):
    """
    FCGI_STDOUT or FCGI_STDERR stream.
    """
    def __init__(self, conn, request_id):
        self.conn = conn
        self.request_id = request_id
        self.closed = False

    def write(self, data):
        if self.closed:
            raise IOError('Writing to closed stream {0}'.format(self))

        if not data:
            return

        write_record = self.conn.write_record
        record_type = self.record_type
        request_id = self.request_id
        size = len(data)

        if size <= FCGI_MAX_CONTENT_LEN:
            record = Record(record_type, data, request_id)
            write_record(record)
        else:
            data = buffer(data)
            sent = 0
            while sent < size:
                record = Record(record_type,
                                data[sent:sent + FCGI_MAX_CONTENT_LEN],
                                request_id)
                write_record(record)
                sent += FCGI_MAX_CONTENT_LEN

    def writelines(self, lines):
        if self.closed:
            raise IOError('Writing to closed stream {0}'.format(self))

        write_record = self.conn.write_record
        record_type = self.record_type
        request_id = self.request_id
        buf = []
        remainder = FCGI_MAX_CONTENT_LEN

        for line in lines:
            if not line:
                # skip empty lines
                continue

            line_len = len(line)

            if line_len >= remainder:
                buf.append(line[:remainder])
                record = Record(record_type, ''.join(buf), request_id)
                write_record(record)
                buf = [line[remainder:]]
                remainder = FCGI_MAX_CONTENT_LEN
            else:
                buf.append(line)
                remainder -= line_len

        if buf:
            record = Record(record_type, ''.join(buf), request_id)
            write_record(record)

    def flush(self):
        pass

    def close(self):
        if not self.closed:
            self.closed = True
            self.conn.write_record(
                Record(self.record_type, '', self.request_id))


class StdoutStream(OutputStream):

    record_type = FCGI_STDOUT

    def writelines(self, lines):
        # WSGI server must not buffer application iterable
        if isinstance(lines, (list, tuple)):
            # ...unless we have all output readily available
            OutputStream.writelines(self, lines)
        else:
            if self.closed:
                raise IOError('Writing to closed stream {0}'.format(self))
            write_record = self.conn.write_record
            record_type = self.record_type
            request_id = self.request_id
            for line in lines:
                if line:
                    record = Record(record_type, line, request_id)
                    write_record(record)


class StderrStream(OutputStream):

    record_type = FCGI_STDERR
