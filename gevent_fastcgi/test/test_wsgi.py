import unittest


class WSITests(unittest.TestCase):

    def test_wsgi_handler(self):
        from gevent_fastcgi.const import FCGI_RESPONDER
        from gevent_fastcgi.base import Connection, Request
        from gevent_fastcgi.wsgi import WSGIRequestHandler
        from .utils import WSGIApplication, MockSocket

        app = WSGIApplication(response='Hello World!')
        handler = WSGIRequestHandler(app)
        request = Request(Connection(MockSocket()), 1, FCGI_RESPONDER)
        handler(request)
