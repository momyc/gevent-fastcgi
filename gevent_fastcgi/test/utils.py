import sys
import os
import errno
from random import random, randint
from functools import wraps
import logging
from zope.interface import implements
from gevent import socket, sleep, signal
from gevent_fastcgi.const import (
    FCGI_RESPONDER,
    FCGI_MAX_CONNS,
    FCGI_MAX_REQS,
    FCGI_MPXS_CONNS,
)
from gevent_fastcgi.base import Record, Connection, pack_pairs
from gevent_fastcgi.wsgi import WSGIServer


logger = logging.getLogger(__name__)


def pack_env(**vars):
    env = {
        'SCRIPT_NAME': '',
        'PATH_INFO': '/',
        'REQUEST_METHOD': 'GET',
        'QUERY_STRING': '',
        'CONTENT_TYPE': 'text/plain',
        'SERVER_NAME': '127.0.0.1',
        'SERVER_PORT': '80',
        'SERVER_PROTOCOL': 'HTTP/1.0',
    }
    if vars:
        env.update(vars)
    return pack_pairs(env)


def some_delay(delay=None):
    if delay is None:
        delay = random * 3
    sleep(delay)


class WSGIApplication(object):

    def __init__(self, response=None, response_headers=None, exception=None,
                 delay=None, slow=False):
        self.exception = exception
        self.response = response
        self.response_headers = response_headers
        self.delay = delay
        self.slow = slow

    def __call__(self, environ, start_response):
        stdin = environ['wsgi.input']

        if not self.delay is None:
            some_delay(self.delay)

        if self.exception is not None:
            stderr = environ['wsgi.errors']
            stderr.write(str(self.exception))
            stderr.flush()
            raise self.exception

        headers = ((self.response_headers is None)
                   and [('Conent-Type', 'text/plain')]
                   or self.response_headers)

        start_response('200 OK', headers)

        if self.response is None:
            response = stdin.read() or self.data
        else:
            response = self.response

        for data in response:
            if self.slow:
                some_delay()
            yield data

    data = map('\n'.__add__, [
        'Lorem ipsum dolor sit amet, consectetur adipisicing elit',
        'sed do eiusmod tempor incididunt ut labore et dolore magna aliqua',
        't enim ad minim veniam, quis nostrud exercitation ullamco',
        'laboris nisi ut aliquip ex ea commodo consequat',
        '',
    ])


class TestingConnection(Connection):

    def write_record(self, record):
        if isinstance(record, Record):
            super(TestingConnection, self).write_record(record)
        else:
            sleep(float(record))


class make_connection(object):

    def __init__(self, address):
        self.address = address

    def __enter__(self):
        if isinstance(self.address, basestring):
            af = socket.AF_UNIX
        else:
            af = socket.AF_INET
        sock = socket.socket(af, socket.SOCK_STREAM)
        sock.connect(self.address)
        self.conn = TestingConnection(sock)
        return self.conn

    def __exit__(self, exc_type, exc_value, traceback):
        self.conn.close()


class wsgi_server(object):
    """ Wrapper around server to ensure it's stopped
    """
    def __init__(self, address=None, app=None, **kw):
        self.address = (address is None
                        and ('127.0.0.1', randint(1024, 65535))
                        or address)
        self.app = app is None and WSGIApplication() or app
        self.kw = kw

    def __enter__(self):
        self.server = WSGIServer(self.address, self.app, **self.kw)
        self.server.start()
        if not hasattr(self.server, 'workers'):
            sys.exit()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.stop()

    def __getattr__(self, attr):
        return getattr(self.server, attr)


def check_socket(callable):
    @wraps(callable)
    def wrapper(self, *args, **kw):
        return callable(self, *args, **kw)
    return wrapper


class MockSocket(object):

    def __init__(self, data=''):
        self.input = data
        self.output = ''
        self.exception = False
        self.closed = False

    def sendall(self, data):
        self.check_socket()
        self.output += data
        self.some_delay()

    def recv(self, max_len=0):
        self.check_socket()
        if not self.input:
            return ''
        if max_len <= 0:
            max_len = self.read_size(len(self.input))
        data = self.input[:max_len]
        self.input = self.input[max_len:]
        self.some_delay()
        return data

    def close(self):
        self.closed = True

    def setsockopt(self, *args):
        pass

    def flip(self):
        self.input, self.output = self.output, ''
        self.closed = False

    def check_socket(self):
        if self.closed:
            raise socket.error(errno.EBADF, 'Closed socket')
        if self.exception:
            raise socket.error(errno.EPIPE, 'Peer closed connection')

    @staticmethod
    def read_size(size):
        if bool(randint(0, 3)):
            size = randint(1, size)
        return size

    @staticmethod
    def some_delay():
        sleep(random() / 27.31)


class MockServer(object):

    def __init__(self, role=FCGI_RESPONDER, max_conns=1024, app=None,
                 response='OK'):
        self.role = role
        self.max_conns = max_conns
        self.app = (app is None) and WSGIApplication() or app
        self.response = response

    def capability(self, name):
        if name == FCGI_MAX_CONNS:
            return str(self.max_conns)
        if name == FCGI_MAX_REQS:
            return str(self.max_conns ** 2)
        if name == FCGI_MPXS_CONNS:
            return '1'
        return ''


class Response(object):

    def __init__(self, request_id):
        self.request_id = request_id
        self.stdout = None
        self.stdout_closed = False
        self.stderr = None
        self.stderr_closed = False
        self.request_status = None
        self.app_status = None

    @property
    def body(self):
        return self.stdout.split('\r\n\r\n', 1)[1]

    @property
    def headers(slef):
        headers = response.split('\r\n\r\n', 1)[0]
        return dict(
            [header.split(': ', 1) for header in headers.split('\r\n')])
