from __future__ import absolute_import

import errno
from random import random, randint, choice
from string import digits, letters, punctuation
from functools import wraps
from contextlib import contextmanager
import logging

from gevent import socket, sleep

from ..const import (
    FCGI_RESPONDER,
    FCGI_MAX_CONNS,
    FCGI_MAX_REQS,
    FCGI_MPXS_CONNS,
    FCGI_MAX_CONTENT_LEN,
)
from ..base import Connection, InputStream
from ..utils import pack_pairs
from ..wsgi import WSGIServer


__all__ = (
    'pack_env',
    'binary_data',
    'text_data',
    'WSGIApplication',
    'TestingConnection',
    'start_wsgi_server',
    'make_connection',
    'MockSocket',
    'MockServer',
    'Response',
)

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


_binary_source = map(chr, range(256))
_text_source = letters + digits + punctuation


def _random_data(source, max_len, min_len):
    if max_len is None:
        size = 137
    elif min_len is None:
        size = max_len
    else:
        if max_len < min_len:
            max_len, min_len = min_len, max_len
        size = randint(min_len, max_len)
    return (choice(source) for _ in xrange(size))


def binary_data(max_len=None, min_len=None):
    return b''.join(_random_data(_binary_source, max_len, min_len))


def text_data(max_len=None, min_len=None):
    return ''.join(_random_data(_text_source, max_len, min_len))


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
            raise self.exception

        headers = ((self.response_headers is None)
                   and [('Conent-Type', 'text/plain')]
                   or self.response_headers)

        start_response('200 OK', headers)

        if self.response is None:
            response = [stdin.read()] or self.data
        elif isinstance(self.response, basestring):
            response = [self.response]
        else:
            response = self.response

        if self.slow:
            some_delay()

        return response

    data = map('\n'.__add__, [
        'Lorem ipsum dolor sit amet, consectetur adipisicing elit',
        'sed do eiusmod tempor incididunt ut labore et dolore magna aliqua',
        't enim ad minim veniam, quis nostrud exercitation ullamco',
        'laboris nisi ut aliquip ex ea commodo consequat',
        '',
    ])


class TestingConnection(Connection):

    def write_record(self, record):
        if isinstance(record, (int, long, float)):
            sleep(record)
        else:
            super(TestingConnection, self).write_record(record)


@contextmanager
def make_connection(address):
    af = isinstance(address, basestring) and socket.AF_UNIX or socket.AF_INET
    sock = socket.socket(af, socket.SOCK_STREAM)
    try:
        sock.connect(address)
        conn = TestingConnection(sock)
        yield conn
    finally:
        sock.close()


@contextmanager
def start_wsgi_server(address=None, app=None, **kw):
    if address is None:
        address = ('127.0.0.1', randint(1024, 65535))
    if app is None:
        app = WSGIApplication()

    server = WSGIServer(address, app, **kw)
    try:
        server.start()
        yield server
    finally:
        server.stop()


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

    def send(self, data, flags=0, timeout=None):
        size = len(data)
        self.check_socket()
        self.output += data[:size]
        #self.some_delay()
        return size

    def sendall(self, data, flags=0):
        self.check_socket()
        self.output += data
        #self.some_delay()

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
        self.stdout = InputStream()
        self.stderr = InputStream()
        self.request_status = None
        self.app_status = None

    def parse(self):
        headers, body = self.stdout.read().split('\r\n\r\n', 1)
        headers = dict(
            header.split(': ', 1) for header in headers.split('\r\n'))
        return headers, body
