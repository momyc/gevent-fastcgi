import sys
import logging
from traceback import format_exception

from gevent_fastcgi.base import (
    InputStream,
    OutputStream,
    FCGI_STDOUT,
    FCGI_STDERR,
)


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


logger = logging.getLogger(__name__)


class Request(object):

    def __init__(self, conn, request_id, role):
        self.conn = conn
        self.id = request_id
        self.role = role
        self.stdin = InputStream()
        self.stdout = OutputStream(conn, request_id, FCGI_STDOUT)
        self.stderr = OutputStream(conn, request_id, FCGI_STDERR)
        self.greenlet = None
        self.environ_list = []
        self.environ = {}
        self.status = None
        self.headers = None
        self.headers_sent = False

    def run(self, app):
        environ = self.make_environ()

        try:
            app_iter = app(environ, self.start_response)
        except:
            app_iter = self.handle_error()
        
        # do nothing until first non-empty chunk
        write = self.stdout.write
        started = self.headers_sent
        for chunk in app_iter:
            if not chunk:
                continue
            if not started:
                started = True
                self.send_headers()
            write(chunk)

        if not started:
            self.send_headers()

        self.stdout.close()
        self.stderr.close()

        if hasattr(app_iter, 'close'):
            app_iter.close()

    def make_environ(self):
        env = self.environ
        
        for name in MANDATORY_WSGI_ENVIRON_VARS.difference(env):
            env[name] = ''

        env['wsgi.version'] = (1, 0)
        env['wsgi.input'] = self.stdin
        env['wsgi.errors'] = self.stderr
        env['wsgi.multithread'] = True
        env['wsgi.multiprocess'] = False
        env['wsgi.run_once'] = False

        https = env.get('HTTPS','').lower()
        if https in ('yes', 'on', '1'):
            env['wsgi.url_scheme'] = 'https'
        else:
            env['wsgi.url_scheme'] = 'http'

        return env

    def start_response(self, status, headers, exc_info=None):
        if exc_info is not None:
            try:
                if self.headers_sent:
                    raise exc_info[1]
            finally:
                exc_info = None
        else:
            assert status is not None
            assert self.status is None

        self.status = status
        self.headers = headers

        return self.write_from_app

    def send_headers(self):
        data = ['Status: %s' % self.status]
        data.extend('%s: %s' % hdr for hdr in self.headers)
        data.append('\r\n')
        self.stdout.write('\r\n'.join(data))
        self.headers_sent = True

    def write_from_app(self, chunk):
        if not chunk:
            return
        if not self.headers_sent:
            self.send_headers()
        self.stdout.write(chunk)

    def handle_error(self):
        exc_info = sys.exc_info()
        logger.exception('Application raised exception')
        self.start_response('500 Internal Server Error', [('Content-type', 'text/plain')], exc_info)
        error_iter = format_exception(*exc_info)
        self.stderr.writelines(error_iter)
        return error_iter
