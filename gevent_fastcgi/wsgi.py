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

import sys
import logging
from traceback import format_exception
import re
from wsgiref.handlers import BaseCGIHandler

from zope.interface import implements

from .interfaces import IRequestHandler
from .server import Request, FastCGIServer


__all__ = ('WSGIRequestHandler', 'WSGIRefRequestHandler', 'WSGIServer')


logger = logging.getLogger(__name__)

MANDATORY_WSGI_ENVIRON_VARS = frozenset((
    'REQUEST_METHOD',
    'SCRIPT_NAME',
    'PATH_INFO',
    'QUERY_STRING',
    'CONTENT_TYPE',
    'CONTENT_LENGTH',
    'SERVER_NAME',
    'SERVER_PORT',
    'SERVER_PROTOCOL',
))


class WSGIRefRequestHandler(object):

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
            start_response('500 Internal Server Error', [
                ('Content-type', 'text/plain'),
            ])
            yield ''


class WSGIRequest(object):

    status_pattern = re.compile(r'^[1-5]\d\d .+$')

    def __init__(self, request):
        self._request = request
        self._status = None
        self._headers = []
        self._headers_sent = False

    def make_environ(self):
        env = self._request.environ

        for name in MANDATORY_WSGI_ENVIRON_VARS.difference(env):
            env[name] = ''

        env['wsgi.version'] = (1, 0)
        env['wsgi.input'] = self._request.stdin
        env['wsgi.errors'] = self._request.stderr
        env['wsgi.multithread'] = True
        env['wsgi.multiprocess'] = False
        env['wsgi.run_once'] = False

        https = env.get('HTTPS', '').lower()
        if https in ('yes', 'on', '1'):
            env['wsgi.url_scheme'] = 'https'
        else:
            env['wsgi.url_scheme'] = 'http'

        return env

    def start_response(self, status, headers, exc_info=None):
        if exc_info is not None:
            try:
                if self._headers_sent:
                    raise exc_info[0], exc_info[1], exc_info[2]
            finally:
                exc_info = None

        self._status = status
        self._headers = headers

        return self._app_write

    def finish(self, app_iter):
        write = self._app_write
        app_iter = iter(app_iter)

        # do nothing until first non-empty item
        for chunk in app_iter:
            if chunk:
                write(chunk)
                break

        if not self._headers_sent:
            self._headers.append(('Content-length', '0'))
            self._send_headers()
        else:
            map(self._request.stdout.write, app_iter)

        self._request.stdout.close()
        self._request.stderr.close()

    def _app_write(self, chunk):
        if not self._headers_sent:
            self._send_headers()
        self._request.stdout.write(chunk)

    def _send_headers(self):
        headers = [('Status', self._status)] + self._headers
        self._request.stdout.writelines(
            ['{0}: {1}\r\n'.format(name, value)
             for name, value in headers]
            + ['\r\n'])
        self._headers_sent = True


class WSGIRequestHandler(object):

    implements(IRequestHandler)

    def __init__(self, app):
        self.app = app

    def __call__(self, request):
        request = WSGIRequest(request)
        environ = request.make_environ()
        try:
            app_iter = self.app(environ, request.start_response)
            request.finish(app_iter)
            if hasattr(app_iter, 'close'):
                app_iter.close()
        except Exception:
            exc_info = sys.exc_info()
            try:
                logger.exception('Application raised exception')
                request.start_response('500 Internal Server Error', [
                    ('Content-type', 'text/plain'),
                ])
                request.finish(map(str, format_exception(*exc_info)))
            finally:
                exc_info = None


class WSGIServer(FastCGIServer):

    def __init__(self, address, app, **kwargs):
        handler = WSGIRequestHandler(app)
        super(WSGIServer, self).__init__(address, handler, **kwargs)
