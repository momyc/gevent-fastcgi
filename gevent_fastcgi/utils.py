try:
    from gevent_fastcgi.speedups import pack_pair, unpack_pairs
except ImportError: # pragma: no cover
    import struct

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
                raise ValueError('Failed to unpack name/value pairs')

def pack_pairs(pairs):
    if isinstance(pairs, dict):
        pairs = pairs.iteritems()

    return ''.join(pack_pair(name, value) for name, value in pairs)


class PartialRead(Exception):
    """ Raised by buffered_reader when it fails to read requested length of data
    """
    def __init__(self, requested_size, partial_data):
        super(PartialRead, self).__init__('Expected %s but received %s bytes only' % (requested_size, len(partial_data)))
        self.requested_size = requested_size
        self.partial_data = partial_data


class BufferedReader(object):
    """ Allows to receive data in large chunks
    """
    def __init__(self, read_callable, buffer_size):
        self._reader = _reader_generator(read_callable, buffer_size)
        self.read_bytes = self._reader.send
        self._reader.next() # advance generator to first yield statement


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
                buf = read((size - blen + buf_size - 1) / buf_size * buf_size)
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
