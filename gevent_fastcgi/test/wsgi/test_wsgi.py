from __future__ import absolute_import

import unittest

from ...wsgi import WSGIRequestHandler, WSGIRefRequestHandler
from ..utils import text_data


class WSGIRequestHandlerBase(object):

    def test_wsgi_handler(self):
        data = [text_data(1, 731) for _ in xrange(137)]

        def app(environ, start_response):
            start_response('222 NotOK', [('Content-type', 'text/plain')])
            return data

        header, body = self._handle_request(app)

        assert header.startswith('Status: 222 NotOK\r\n')
        assert body == ''.join(data)

    def test_write(self):
        data = [text_data(1, 7) for _ in xrange(13)]

        def app(environ, start_response):
            write = start_response('500 Internal server error',
                                   [('Content-type', 'text/plain')])
            map(write, data)
            return []

        header, body = self._handle_request(app)

        assert header.startswith('Status: 500 Internal server error\r\n')
        assert body == ''.join(data)

    def test_write_and_iterable(self):
        data = [text_data(1, 7) for _ in xrange(13)]
        cut = 5

        def app(environ, start_response):
            write = start_response('200 OK',
                                   [('Content-type', 'text/plain')])
            # start using write
            map(write, data[:cut])
            # and the rest is as iterator
            return iter(data[cut:])

        header, body = self._handle_request(app)

        assert header.startswith('Status: 200 OK\r\n')
        assert body == ''.join(data)

    def _handle_request(self, app):
        from ...const import FCGI_STDOUT, FCGI_RESPONDER
        from ...base import Connection
        from ...server import Request
        from ..utils import text_data, MockSocket

        sock = MockSocket()
        conn = Connection(sock)
        request = Request(conn, 1, FCGI_RESPONDER)

        handler = self.handler_class(app)
        handler(request)

        sock.flip()

        stdout = ''.join(
            record.content for record in conn
            if record.type == FCGI_STDOUT)

        return stdout.split('\r\n\r\n', 1)


class WSGIRequestHandlerTests(WSGIRequestHandlerBase, unittest.TestCase):

    handler_class = WSGIRequestHandler


class WSGIRefRequestHandlerTests(WSGIRequestHandlerBase, unittest.TestCase):

    handler_class = WSGIRefRequestHandler
