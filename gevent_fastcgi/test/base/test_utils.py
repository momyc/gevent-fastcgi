from __future__ import absolute_import

import os
import unittest

from ..utils import binary_data


class UtilsTests(unittest.TestCase):

    def test_pack_unpack(self):
        from ...utils import pack_pairs, unpack_pairs

        pairs = os.environ.items()
        for pair_in, pair_out in zip(pairs, unpack_pairs(pack_pairs(pairs))):
            assert pair_in == pair_out

    def test_pack_unpack_header(self):
        from ...const import FCGI_VERSION, FCGI_BEGIN_REQUEST
        from ...utils import pack_header, unpack_header

        raw_data = (FCGI_VERSION, FCGI_BEGIN_REQUEST, 31731, 17317, 137)
        assert raw_data == unpack_header(pack_header(*raw_data))

    def test_pack_unpack_begin_request(self):
        from ...const import FCGI_AUTHORIZER, FCGI_KEEP_CONN
        from ...utils import pack_begin_request, unpack_begin_request

        raw_data = (FCGI_AUTHORIZER, FCGI_KEEP_CONN)
        assert raw_data == unpack_begin_request(pack_begin_request(*raw_data))

    def test_pack_unpack_end_request(self):
        from ...const import FCGI_UNKNOWN_ROLE
        from ...utils import pack_end_request, unpack_end_request

        raw_data = (924, FCGI_UNKNOWN_ROLE)
        assert raw_data == unpack_end_request(pack_end_request(*raw_data))

    def test_pack_unpack_unknown_type(self):
        from ...utils import pack_unknown_type, unpack_unknown_type

        raw_data = (173,)
        assert raw_data == unpack_unknown_type(pack_unknown_type(*raw_data))

    def test_buffered_reader(self):
        from ...base import BufferedReader

        sizes = [1, 13, 137, 1371, 13713]
        data = binary_data(max(sizes) + 137)

        def read(size):
            return data[:size]

        for size in sizes:
            reader = BufferedReader(read, 173)
            chunk = reader.read_bytes(size)
            assert len(chunk) == size
            assert data.startswith(chunk)
