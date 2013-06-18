from __future__ import absolute_import

import unittest

from ...const import FCGI_STDERR, FCGI_NULL_REQUEST_ID, FCGI_MAX_CONTENT_LEN
from ...base import Record

from ..utils import binary_data


class RecordTests(unittest.TestCase):

    def test_constructor(self):
        record_type = FCGI_STDERR
        content = binary_data()
        request_id = 1

        self.assertRaises(TypeError, Record)

        record = Record(record_type)
        assert record.type == record_type
        assert record.content == ''
        assert record.request_id == FCGI_NULL_REQUEST_ID

        record = Record(record_type, content)
        assert record.type == record_type
        assert record.content == content
        assert record.request_id == FCGI_NULL_REQUEST_ID

        record = Record(record_type, content, request_id)
        assert record.type == record_type
        assert record.content == content
        assert record.request_id == request_id
