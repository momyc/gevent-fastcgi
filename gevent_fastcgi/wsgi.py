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

import logging
from wsgiref.handlers import BaseCGIHandler

from zope.interface import implements

from gevent_fastcgi.interfaces import IRequestHandler
from gevent_fastcgi.server import FastCGIServer


__all__ = ('WSGIRequestHandler', 'WSGIServer')


logger = logging.getLogger(__name__)


class WSGIRequestHandler(object):

    implements(IRequestHandler)

    def __init__(self, app):
        self.app = app

    def __call__(self, request):
        handler = self.CGIHandler(request)
        handler.run(self.app)

    class CGIHandler(BaseCGIHandler):

        def __init__(self, request):
            BaseCGIHandler.__init__(self, request.stdin, request.stdout,
                                    request.stderr, request.environ)

        def log_exception(self, exc_info):
            logger.exception('WSGI application failed')

        def error_output(self, environ, start_response):
            start_response('500 Internal Server Error', [('Content-type', 'text/plain')])
            yield ''


class WSGIServer(FastCGIServer):

    def __init__(self, address, app, **kwargs):
        handler = WSGIRequestHandler(app)
        super(WSGIServer, self).__init__(address, handler, **kwargs)
