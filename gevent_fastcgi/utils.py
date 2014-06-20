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

from __future__ import absolute_import

import struct
import logging


__all__ = [
    'pack_pairs',
    'unpack_pairs',
]

logger = logging.getLogger(__name__)

header_struct = struct.Struct('!BBHHBx')
begin_request_struct = struct.Struct('!HB5x')
end_request_struct = struct.Struct('!LB3x')
unknown_type_struct = struct.Struct('!B7x')

for name in 'header', 'begin_request', 'end_request', 'unknown_type':
    packer = globals().get('{}_struct'.format(name))
    for prefix, attr in (
        ('pack_', 'pack'),
        ('unpack_', 'unpack_from'),
    ):
        full_name = prefix + name
        globals()[full_name] = getattr(packer, attr)
        __all__.append(full_name)


def pack_pairs(pairs):
    if isinstance(pairs, dict):
        pairs = pairs.iteritems()
    return ''.join(pack_pair(name, value) for name, value in pairs)


try:
    from .speedups import pack_pair, unpack_pairs
    logger.debug('Using speedups module')
except ImportError:
    logger.debug('Failed to load speedups module')

    length_struct = struct.Struct('!L')

    def pack_len(s):
        l = len(s)
        if l < 128:
            return chr(l)
        elif l > 0x7fffffff:
            raise ValueError('Maximum name or value length is {0}'.format(
                0x7fffffff))
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
            except (IndexError, struct.error):
                raise ValueError('Buffer is too short')

            if end - pos < name_len + value_len:
                raise ValueError('Buffer is {0} bytes short'.format(
                    name_len + value_len - (end - pos)))
            name = data[pos:pos + name_len]
            pos += name_len
            value = data[pos:pos + value_len]
            pos += value_len
            yield name, value
