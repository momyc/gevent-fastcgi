from __future__ import absolute_import

import sys
import unittest
import six
from six.moves import xrange

from gevent_fastcgi.const import FCGI_STDOUT, FCGI_RESPONDER
from gevent_fastcgi.base import Connection
from gevent_fastcgi.server import Request
from gevent_fastcgi.wsgi import WSGIRequestHandler, WSGIRefRequestHandler
from ..utils import text_data, MockSocket, text_data


class WSGIRequestHandlerBase(object):

    def test_wsgi_handler(self):
        data = [text_data(1, 731).encode("ISO-8859-1") for _ in xrange(137)]

        def app(environ, start_response):
            start_response('222 NotOK', [('Content-type', 'text/plain')])
            return data

        header, body = self._handle_request(app)

        assert header.startswith(b'Status: 222 NotOK\r\n')
        assert body == b''.join(data)

    def test_write(self):
        data = [text_data(1, 7).encode("ISO-8859-1") for _ in xrange(13)]

        def app(environ, start_response):
            write = start_response('500 Internal server error',
                                   [('Content-type', 'text/plain')])
            list(map(write, data))
            return []

        header, body = self._handle_request(app)

        assert header.startswith(b'Status: 500 Internal server error\r\n')
        assert body == b''.join(data)

    def test_write_and_iterable(self):
        data = [text_data(1, 7).encode("ISO-8859-1") for _ in xrange(13)]
        cut = 5

        def app(environ, start_response):
            write = start_response('200 OK',
                                   [('Content-type', 'text/plain')])
            # start using write
            list(map(write, data[:cut]))
            # and the rest is as iterator
            return iter(data[cut:])

        header, body = self._handle_request(app)

        assert header.startswith(b'Status: 200 OK\r\n')
        assert body == b''.join(data)

    def test_iterable_with_close(self):

        class Result(object):
            def __init__(self, data):
                self.data = data
                self.closed = False

            def __iter__(self):
                return iter(self.data)

            def close(self):
                self.closed = True

        data = [text_data(1, 73) for _ in range(13)]
        data = [line.encode("ISO-8859-1") for line in data]
        result = Result(data)

        def app(environ, start_response):
            start_response('200 OK', [('Content-type', 'text/plain')])
            return result

        header, body = self._handle_request(app)

        assert header.startswith(b'Status: 200 OK\r\n')
        assert body == b''.join(data)
        assert result.closed

    def test_app_exception(self):
        def app(environ, start_response):
            start_response('200 OK', [('Content-type', 'text/plain')])
            raise NameError("LETS_MAKE_SOME_MESS")

        header, body = self._handle_request(app)

        assert header.startswith(b'Status: 500 ')

    def test_start_response_with_exc_info(self):
        error_message = b'Bad things happen'

        def app(environ, start_response):
            try:
                raise NameError("LETS_MAKE_SOME_MESS")
            except NameError:
                start_response('200 OK', [('Content-type', 'text/plain')],
                               sys.exc_info())
                return [error_message]

        header, body = self._handle_request(app)

        assert header.startswith(b'Status: 200 OK\r\n')
        assert body == error_message

    def test_start_response_with_exc_info_headers_sent(self):
        greetings = b'Hello World!\r\n'
        error_message = b'Bad things happen'

        def app(environ, start_response):
            start_response('200 OK', [('Content-type', 'text/plain')])
            # force headers to be sent
            yield greetings
            try:
                raise NameError("LETS_MAKE_SOME_MESS")
            except NameError:
                start_response('500 ' + error_message.decode("utf-8"),
                               [('Content-type', 'text/plain')],
                               sys.exc_info())
                yield error_message

        header, body = self._handle_request(app)

        assert header.startswith(b'Status: 200 OK\r\n'), header
        assert body.startswith(greetings)

    def _handle_request(self, app):
        sock = MockSocket()
        conn = Connection(sock)
        request = Request(conn, 1, FCGI_RESPONDER)

        handler = self.handler_class(app)
        handler(request)

        sock.flip()

        stdout = b''.join(
            record.content for record in conn
            if record.type == FCGI_STDOUT)

        return stdout.split(b'\r\n\r\n', 1)


class WSGIRequestHandlerTests(WSGIRequestHandlerBase, unittest.TestCase):

    handler_class = WSGIRequestHandler


class WSGIRefRequestHandlerTests(WSGIRequestHandlerBase, unittest.TestCase):

    handler_class = WSGIRefRequestHandler
