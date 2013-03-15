import sys
import os
import errno
from random import random, randint
import logging
from zope.interface import implements
from gevent import socket, sleep, signal
from gevent_fastcgi.const import FCGI_RESPONDER, FCGI_MAX_CONNS, FCGI_MAX_REQS, FCGI_MPXS_CONNS
from gevent_fastcgi.base import Record, Connection, pack_pairs
from gevent_fastcgi.server import FastCGIServer
from gevent_fastcgi.wsgi import WSGIRequestHandler


logger = logging.getLogger(__name__)
data = map('\n'.__add__, [
    'Lorem ipsum dolor sit amet, consectetur adipisicing elit',
    'sed do eiusmod tempor incididunt ut labore et dolore magna aliqua',
    't enim ad minim veniam, quis nostrud exercitation ullamco',
    'laboris nisi ut aliquip ex ea commodo consequat',
    '',
])


def dice():
    return bool(randint(0, 3))


def delay():
    sleep(random() / 27.31)


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


def response_body(response):
    return response.split('\r\n\r\n', 1)[1]


def response_headers(response):
    headers = response.split('\r\n\r\n', 1)[0]
    return [header.split(': ', 1) for header in headers.split('\r\n')]


def app(environ, start_response):
    stdin = environ['wsgi.input']
    stdin.read()
    write = start_response('200 OK', [])
    stderr = environ['wsgi.errors']
    stderr.writelines(data)
    stderr.flush()
    write('')
    map(write, data)
    return ['', ''] + data


def slow_app(environ, start_response):
    logger.debug('Starting slow app')
    stdin = environ['wsgi.input']
    for line in stdin:
        pass
    start_response('200 OK', [])
    
    def response():
        for line in data:
            sleep(1)
            yield line
    return response()


def echo_app(environ, start_response):
    from StringIO import StringIO

    start_response('200 OK', [])
    response = StringIO(environ['wsgi.input'].read())
    return response


def failing_app(environ, start_response):
    start_response('200 OK', [])
    raise AssertionError('This is simulation of exception in application')


def failing_app2(environ, start_response):
    write = start_response('200 OK', [])
    map(write, data)
    raise AssertionError('This is simulation of exception in application')


def empty_app(environ, start_response):
    start_response('200 OK', [])
    return []


class TestingConnection(Connection):

    def write_record(self, record):
        if isinstance(record, Record):
            super(TestingConnection, self).write_record(record)
            sleep(0)
        else:
            sleep(record)


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


class start_server(object):
    """ Wrapper around server to ensure it's stopped
    """
    def __init__(self, address=None, app=app, fork=False, **kw):
        if address is None:
            address = ('127.0.0.1', randint(1024, 65535))
        self.address = address
        self.app = app
        if fork:
            logger.warn('No forking in testing mode!')
        self.fork = False # no forking
        self.kw = kw

    def __enter__(self):
        if self.fork:
            pid = os.fork()
            if pid:
                self.pid = pid
                sleep(1)
            else:
                request_handler = WSGIRequestHandler(self.app)
                server = FastCGIServer(self.address, request_handler, **self.kw)
                signal(15, server.stop)
                server.serve_forever()
                sys.exit()
        else:
            request_handler = WSGIRequestHandler(self.app)
            self.server = FastCGIServer(self.address, request_handler, **self.kw)
            self.server.start()
        return self
        

    def __exit__(self, exc_type, exc_value, traceback):
        if self.fork:
            if hasattr(self, 'pid'):
                self._kill()
        else:
            self.server.stop()

    def __getattr__(self, attr):
        return getattr(self.server, attr)

    def _kill(self):
        try:
            os.kill(self.pid, 15)
        finally:
            os.waitpid(self.pid, 0)
    

class MockSocket(object):

    def __init__(self, data=''):
        self.input = data
        self.output = ''
        self.fail = False
        self.closed = False

    def sendall(self, data):
        if self.closed:
            raise ValueError('I/O operation on closed socket')
        if self.fail:
            raise socket.error(errno.EPIPE, 'Peer closed connection')
        self.output += data
        delay()

    def recv(self, max_len=0):
        if self.closed:
            raise socket.error(errno.EBADF, 'Closed socket')
        if self.fail:
            raise socket.error(errno.EPIPE, 'Peer closed connection')
        if not self.input:
            return ''
        if max_len <= 0:
            max_len = len(self.input)
        if not dice():
            max_len = randint(1, max_len)
        data = self.input[:max_len]
        self.input = self.input[max_len:]
        delay()
        return data

    def close(self):
        self.closed = True

    def setsockopt(self, *args):
        pass

    def flip(self):
        self.input, self.output = self.output, ''
        self.closed = False


class MockServer(object):

    def __init__(self, role=FCGI_RESPONDER, max_conns=1024, app=app, response='OK'):
        self.role = role
        self.max_conns = max_conns
        self.app = app
        self.response = response

    def capability(self, name):
        if name == FCGI_MAX_CONNS:
            return str(self.max_conns)
        if name == FCGI_MAX_REQS:
            return str(self.max_conns ** 2)
        if name == FCGI_MPXS_CONNS:
            return '1'
        return ''


