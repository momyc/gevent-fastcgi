from __future__ import absolute_import

import unittest


class WSGITests(unittest.TestCase):

    def test_wsgi_handler(self):
        from ...wsgi import WSGIRequestHandler, WSGIRefRequestHandler

        for handler_class in WSGIRequestHandler, WSGIRefRequestHandler:
            self._test_handler_class(handler_class)

    def _test_handler_class(self, handler_class):
        from ...const import FCGI_STDOUT, FCGI_RESPONDER
        from ...base import Connection
        from ...server import Request
        from ..utils import text_data, MockSocket

        sock = MockSocket()
        conn = Connection(sock)
        request = Request(conn, 1, FCGI_RESPONDER)
        data = [text_data(1, 731) for _ in xrange(137)]

        def app(environ, start_response):
            start_response('222 NotOK', [('Content-type', 'text/plain')])
            return data

        handler = handler_class(app)
        handler(request)

        sock.flip()

        stdout = ''.join(record.content for record in conn
                         if record.type == FCGI_STDOUT)
        header, body = stdout.split('\r\n\r\n', 1)

        assert header.startswith('Status: 222 NotOK\r\n')
        assert body == ''.join(data)
