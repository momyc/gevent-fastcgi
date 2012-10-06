import errno
from random import random, randint
import logging
from zope.interface import implements
from gevent import socket, sleep
from gevent_fastcgi.interfaces import IServer
from gevent_fastcgi.base import (
    pack_pairs,
    FCGI_RESPONDER,
    FCGI_MAX_CONNS,
    FCGI_MAX_REQS,
    FCGI_MPXS_CONNS,
    Connection
    )
from gevent_fastcgi.server import WSGIServer


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


class IterWithClose(object):

    def __init__(self, orig):
        self.iter = iter(orig)

    def __iter__(self):
        return self

    def next(self):
        return self.iter.next()

    def close(self):
        logger.debug('%s.close was called' % self.__class__.__name__)


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
    stdin.read()
    start_response('200 OK', [])
    sleep(3)
    return data


def echo_app(environ, start_response):
    start_response('200 OK', [])
    return IterWithClose(environ['wsgi.input'])


def failing_app(environ, start_response):
    start_response('200 OK', [])
    assert False, 'Something really bad happened!!!'


def failing_app2(environ, start_response):
    write = start_response('200 OK', [])
    map(write, data)
    assert False, 'Something really bad happened!!!'


def empty_app(environ, start_response):
    start_response('200 OK', [])
    return []


default_address = ('127.0.0.1', 47968)


class make_server(object):
    """ Wrapper around server to ensure it's stopped
    """
    def __init__(self, address=default_address, app=app, **kw):
        self.server = WSGIServer(address, app, **kw)
        self.server.start()

    def __enter__(self):
        return self.server

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.stop()

    def __del__(self):
        if hasattr(self, 'server'):
            self.server.stop()


class TestingConnection(Connection):

    def write_record(self, record):
        if isinstance(record, (int, long, float)):
            sleep(record)
        else:
            super(TestingConnection, self).write_record(record)


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


class make_server_conn(object):
    
    def __init__(self, address=default_address, app=app, **server_params):
        self.address = address
        self.app = app
        self.server_params = server_params

    def __enter__(self):
        self.server = WSGIServer(self.address, self.app, **self.server_params)
        self.server.start()
        self.conn = make_connection(self.address)
        return self.conn.__enter__()
    
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.conn.__exit__(exc_type, exc_value, traceback)
        finally:
            self.server.stop()
    

class MockSocket(object):

    def __init__(self, data=''):
        self.input = data
        self.output = ''
        self.fail = False
        self.closed = False

    def sendall(self, data):
        if self.closed:
            raise socket.error(errno.EBADF, 'Closed socket')
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

    implements(IServer)

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


