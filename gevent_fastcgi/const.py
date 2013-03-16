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

import struct


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
