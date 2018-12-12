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
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from __future__ import with_statement, absolute_import

from gevent.monkey import patch_os
patch_os()

import os
import sys
import errno
import logging
from signal import SIGHUP, SIGKILL, SIGQUIT, SIGINT, SIGTERM
import atexit

from zope.interface import implements

from gevent import sleep, spawn, socket, signal, version_info
from gevent.server import StreamServer
from gevent.event import Event
try:
    from gevent.lock import Semaphore
except ImportError:
    from gevent.coros import Semaphore

from .interfaces import IRequest
from .const import (
    FCGI_ABORT_REQUEST,
    FCGI_AUTHORIZER,
    FCGI_BEGIN_REQUEST,
    FCGI_END_REQUEST,
    FCGI_FILTER,
    FCGI_GET_VALUES,
    FCGI_GET_VALUES_RESULT,
    FCGI_KEEP_CONN,
    FCGI_NULL_REQUEST_ID,
    FCGI_PARAMS,
    FCGI_REQUEST_COMPLETE,
    FCGI_RESPONDER,
    FCGI_STDIN,
    FCGI_DATA,
    FCGI_UNKNOWN_ROLE,
    FCGI_UNKNOWN_TYPE,
    EXISTING_REQUEST_RECORD_TYPES,
)
from .base import (
    Connection,
    Record,
    InputStream,
    StdoutStream,
    StderrStream,
)
from .utils import (
    pack_pairs,
    unpack_pairs,
    unpack_begin_request,
    pack_end_request,
    pack_unknown_type,
)


__all__ = ('Request', 'ServerConnection', 'FastCGIServer')

logger = logging.getLogger(__name__)


class Request(object):

    implements(IRequest)

    def __init__(self, conn, request_id, role):
        self.conn = conn
        self.id = request_id
        self.role = role
        self.environ = {}
        self.stdin = InputStream()
        self.stdout = StdoutStream(conn, request_id)
        self.stderr = StderrStream(conn, request_id)
        self.greenlet = None
        self._environ = InputStream()


class ServerConnection(Connection):

    def __init__(self, *args, **kw):
        super(ServerConnection, self).__init__(*args, **kw)
        self.lock = Semaphore()

    def write_record(self, record):
        # We must serialize access for possible multiple request greenlets
        with self.lock:
            super(ServerConnection, self).write_record(record)


HANDLE_RECORD_ATTR = '_handle_record_type'


def record_handler(record_type):
    """
    Mark method as a tecord handler of this record type
    """
    def decorator(method):
        setattr(method, HANDLE_RECORD_ATTR, record_type)
        return method
    return decorator


class ConnectionHandler(object):

    class __metaclass__(type):
        """
        Collect record handlers during class construction
        """
        def __new__(cls, name, bases, attrs):
            attrs['_record_handlers'] = dict(
                (getattr(method, HANDLE_RECORD_ATTR), method)
                for name, method in attrs.items()
                if hasattr(method, HANDLE_RECORD_ATTR))
            return type(name, bases, attrs)

    def __init__(self, conn, role, capabilities, request_handler):
        self.conn = conn
        self.role = role
        self.capabilities = capabilities
        self.request_handler = request_handler
        self.requests = {}
        self.keep_open = None
        self.closing = False
        self._job_is_done = Event()

    def run(self):
        reader = spawn(self.read_records)
        reader.link(self._report_finished_job)
        event = self._job_is_done

        while True:
            event.wait()
            event.clear()
            logger.debug('Checking if connection can be closed now')
            if self.requests:
                logger.debug('Connection left open due to active requests')
            elif self.keep_open and not reader.ready():
                logger.debug('Connection left open due to KEEP_CONN flag')
            else:
                break

        reader.kill()
        reader.join()
        logger.debug('Closing connection')
        self.conn.close()

    def handle_request(self, request):
        try:
            logger.debug('Handling request {0}'.format(request.id))
            self.request_handler(request)
        except:
            logger.exception('Request handler raised exception')
            raise
        finally:
            self.end_request(request)

    def end_request(self, request, request_status=FCGI_REQUEST_COMPLETE,
                    app_status=0):
        try:
            request.stdout.close()
            request.stderr.close()
            self.send_record(FCGI_END_REQUEST, pack_end_request(
                app_status, request_status), request.id)
        finally:
            del self.requests[request.id]
            logger.debug('Request {0} ended'.format(request.id))

    def read_records(self):
        record_handlers = self._record_handlers
        requests = self.requests
        for record in self.conn:
            handler = record_handlers.get(record.type)
            if handler is None:
                logger.error('{0}: Unknown record type'.format(record))
                self.send_record(FCGI_UNKNOWN_TYPE,
                                 pack_unknown_type(record.type))
                break

            if record.type in EXISTING_REQUEST_RECORD_TYPES:
                request = requests.get(record.request_id)
                if request is None:
                    logger.error(
                        'Record {0} for non-existent request'.format(record))
                    break
                handler(self, record, request)
            else:
                handler(self, record)

    def send_record(
            self, record_type, content='', request_id=FCGI_NULL_REQUEST_ID):
        self.conn.write_record(Record(record_type, content, request_id))

    @record_handler(FCGI_GET_VALUES)
    def handle_get_values_record(self, record):
        pairs = ((name, self.capabilities.get(name)) for name, _ in
                 unpack_pairs(record.content))
        content = pack_pairs(
            (name, str(value)) for name, value in pairs)
        self.send_record(FCGI_GET_VALUES_RESULT, content)
        self._report_finished_job()

    @record_handler(FCGI_BEGIN_REQUEST)
    def handle_begin_request_record(self, record):
        role, flags = unpack_begin_request(record.content)
        if role != self.role:
            self.send_record(FCGI_END_REQUEST, pack_end_request(
                0,  FCGI_UNKNOWN_ROLE), record.request_id)
            logger.error(
                'Request role {0} does not match server role {1}'.format(
                    role, self.role))
            self._report_finished_job()
        else:
            # Should we check this for every request instead?
            if self.keep_open is None:
                self.keep_open = bool(FCGI_KEEP_CONN & flags)
            request = Request(self.conn, record.request_id, role)
            if role == FCGI_FILTER:
                request.data = InputStream()
            self.requests[request.id] = request

    @record_handler(FCGI_STDIN)
    def handle_stdin_record(self, record, request):
        request.stdin.feed(record.content)

    @record_handler(FCGI_DATA)
    def handle_data_record(self, record, request):
        request.data.feed(record.content)
        if not record.content and request.role == FCGI_FILTER:
            self.spawn_request_handler(request)

    @record_handler(FCGI_PARAMS)
    def handle_params_record(self, record, request):
        request._environ.feed(record.content)
        if not record.content:
            # EOF received
            request.environ = dict(unpack_pairs(request._environ.read()))
            del request._environ
            if request.role in (FCGI_RESPONDER, FCGI_AUTHORIZER):
                self.spawn_request_handler(request)

    @record_handler(FCGI_ABORT_REQUEST)
    def handle_abort_request_record(self, record, request):
        logger.warn('Aborting request {0}'.format(request.id))
        if request.id in self.requests:
            greenlet = request.greenlet
            if greenlet is None:
                self.end_request(request)
                self._report_finished_job()
            else:
                logger.warn('Killing greenlet {0} for request {1}'.format(
                    greenlet, request.id))
                greenlet.kill()
                greenlet.join()
        else:
            logger.debug('Request {0} not found'.format(request.id))

    def spawn_request_handler(self, request):
        request.greenlet = g = spawn(self.handle_request, request)
        g.link(self._report_finished_job)

    def _report_finished_job(self, source=None):
        self._job_is_done.set()


class FastCGIServer(StreamServer):
    """
    Server that handles communication with Web-server via FastCGI protocol.
    It is request_handler's responsibility to choose protocol and deal with
    application invocation. gevent_fastcgi.wsgi module contains WSGI
    protocol implementation.
    """

    def __init__(self, listener, request_handler, role=FCGI_RESPONDER,
                 num_workers=1, buffer_size=1024, max_conns=1024,
                 socket_mode=None, **kwargs):
        # StreamServer does not create UNIX-sockets
        if isinstance(listener, basestring):
            self._socket_file = listener
            self._socket_mode = socket_mode
            # StreamServer does not like "backlog" with pre-cooked socket
            self._backlog = kwargs.pop('backlog', None)
            if self._backlog is None:
                self._backlog = max_conns
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        super(FastCGIServer, self).__init__(
            listener, self.handle_connection, spawn=max_conns, **kwargs)

        if role not in (FCGI_RESPONDER, FCGI_FILTER, FCGI_AUTHORIZER):
            raise ValueError('Illegal FastCGI role {0}'.format(role))

        self.max_conns = max_conns
        self.role = role
        self.request_handler = request_handler
        self.buffer_size = buffer_size
        self.capabilities = dict(
            FCGI_MAX_CONNS=str(max_conns),
            FCGI_MAX_REQS=str(max_conns * 1024),
            FCGI_MPXS_CONNS='1',
        )

        self.num_workers = int(num_workers)
        assert self.num_workers > 0, 'num_workers must be positive number'
        self._workers = []

    def start(self):
        logger.debug('Starting server')
        if not self.started:
            if hasattr(self, '_socket_file'):
                self._create_socket_file()
            super(FastCGIServer, self).start()
            if self.num_workers > 1:
                self._start_workers()
                self._supervisor = spawn(self._watch_workers)
                atexit.register(self._cleanup)
                for signum in SIGINT, SIGTERM, SIGQUIT:
                    signal(signum, sys.exit, 1)

    def start_accepting(self):
        # master proceess with workers should not start accepting
        if self._workers is None or self.num_workers == 1:
            super(FastCGIServer, self).start_accepting()

    def stop_accepting(self):
        # master proceess with workers did not start accepting
        if self._workers is None or self.num_workers == 1:
            super(FastCGIServer, self).stop_accepting()

    def handle_connection(self, sock, addr):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            sock.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF,
                            self.buffer_size)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF,
                            self.buffer_size)
        conn = ServerConnection(sock, self.buffer_size)
        handler = ConnectionHandler(
            conn, self.role, self.capabilities, self.request_handler)
        handler.run()

    if version_info < (1,):
        # older version of gevent
        def kill(self):
            super(FastCGIServer, self).kill()
            self._cleanup()
    else:
        def close(self):
            super(FastCGIServer, self).close()
            self._cleanup()

    def _start_workers(self):
        while len(self._workers) < self.num_workers:
            self._start_worker()

    def _start_worker(self):
        pid = os.fork()
        if pid:
            # master process
            self._workers.append(pid)
            logger.debug('Started worker {0}'.format(pid))
            return pid
        else:
            try:
                # this indicates current process is a worker
                self._workers = None
                devnull_fd = os.open(os.devnull, os.O_RDWR)
                try:
                    for fd in (0,):
                        os.dup2(devnull_fd, fd)
                finally:
                    os.close(devnull_fd)
                signal(SIGHUP, self.stop)
                self.start_accepting()
                super(FastCGIServer, self).serve_forever()
            finally:
                # worker must never return
                os._exit(0)

    def _watch_workers(self, check_interval=5):
        keep_running = True
        while keep_running:
            self._start_workers()

            try:
                try:
                    sleep(check_interval)
                    self._reap_workers()
                except self.Stop:
                    logger.debug('Waiting for all workers to exit')
                    keep_running = False
                    self._reap_workers(True)
            except OSError, e:
                if e.errno != errno.ECHILD:
                    logger.exception('Failed to wait for any worker to exit')
                else:
                    logger.debug('No alive workers left')

    def _reap_workers(self, block=False):
        flags = 0 if block else os.WNOHANG
        while self._workers:
            pid, status = os.waitpid(-1, flags)
            if pid == 0:
                break
            elif pid in self._workers:
                logger.debug('Worker {0} exited'.format(pid))
                self._workers.remove(pid)

    def _cleanup(self):
        if hasattr(self, '_workers'):
            # it was initialized
            if self._workers is not None:
                # master process
                try:
                    self._kill_workers()
                finally:
                    self._remove_socket_file()
        else:
            # _workers was not initialized but it's still master process
            self._remove_socket_file()

    def _kill_workers(self, kill_timeout=2):
        for pid, sig in self._killing_sequence(kill_timeout):
            try:
                logger.debug(
                    'Killing worker {0} with signal {1}'.format(pid, sig))
                os.kill(pid, sig)
            except OSError, x:
                if x.errno == errno.ESRCH:
                    logger.error('Worker with pid {0} not found'.format(pid))
                    if pid in self._workers:
                        self._workers.remove(pid)
                elif x.errno == errno.ECHILD:
                    logger.error('No alive workers left')
                    self._workers = []
                    break
                else:
                    logger.exception(
                        'Failed to kill worker {0} with signal {1}'.format(
                            pid, sig))

    def _killing_sequence(self, max_timeout):
        short_delay = max(0.1, max_timeout / 50)
        for sig in SIGHUP, SIGKILL:
            if not self._workers:
                raise StopIteration
            logger.debug('Killing workers {0} with signal {1}'.
                         format(self._workers, sig))
            for pid in self._workers[:]:
                yield pid, sig

            sleep(short_delay)
            self._supervisor.kill(self.Stop)
            sleep(short_delay)
            if self._workers:
                sleep(max_timeout)

    def _create_socket_file(self):
        if self._socket_mode is not None:
            umask = os.umask(0)
            try:
                self.socket.bind(self._socket_file)
                os.chmod(self._socket_file, self._socket_mode)
            finally:
                os.umask(umask)
        else:
            self.socket.bind(self._socket_file)

        self.socket.listen(self._backlog)

    def _remove_socket_file(self):
        socket_file = self.__dict__.pop('_socket_file', None)
        if socket_file:
            try:
                logger.debug('Removing socket-file {0}'.format(socket_file))
                os.unlink(socket_file)
            except OSError:
                logger.exception(
                    'Failed to remove socket file {0}'
                    .format(socket_file))

    class Stop(BaseException):
        """ Used to signal watcher greenlet
        """
