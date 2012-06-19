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


from logging import getLogger
from struct import pack, unpack

from gevent import socket

from gevent_fastcgi.base import *


__all__ = ('ClientConnection',)


logger = getLogger(__name__)


class ClientConnection(BaseConnection):
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
        self.write_record(Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(role, flags), request_id))

    def send_abort_request(self, request_id):
        self.write_record(Record(FCGI_ABORT_REQUEST, request_id=request_id))

    def send_params(self, params, request_id):
        if params:
            params = ''.join(pack_pairs(params))
        else:
            params = ''
        self.send_stream(FCGI_PARAMS, params, request_id)

    def send_stream(self, stream, content='', request_id=1):
        content_len = len(content)
        if content_len <= 0xffff:
            self.write_record(Record(stream, content, request_id))
        else:
            sent = 0
            while sent < content_len:
                chunk_len = min(content_len - sent, 0xffff)
                self.write_record(Record(stream, content[sent:sent + chunk_len], request_id))
                sent += chunk_len

    def send_get_values(self, names):
        content = pack_pairs((name, '') for name in names)
        self.write_record(Record(FCGI_GET_VALUES, content))

    def unpack_end_request(self, data):
        return end_request_struct.unpack(data)

