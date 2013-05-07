# Copyright (c) 2011-2013, Alexander Kulakov
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#    The above copyright notice and this permission notice shall be included in
#    all copies or substantial portions of the Software.
#
#    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#    DEALINGS IN THE SOFTWARE.

from __future__ import with_statement

import sys
import os
import logging
from signal import SIGHUP, SIGCHLD, SIGTERM, SIGINT

from gevent.monkey import patch_os; patch_os()
from gevent import spawn, socket, signal
from gevent.server import StreamServer
from gevent.coros import Semaphore
from gevent.event import Event

from gevent_fastcgi.const import *
from gevent_fastcgi.base import (
        Connection, 
        Record, 
        InputStream, 
        Request, 
        pack_pairs, 
        unpack_pairs,
        )


__all__ = ('ServerConnection', 'FastCGIServer')

logger = logging.getLogger(__name__)


EXISTING_REQUEST_REC_TYPES = frozenset((
    FCGI_STDIN,
    FCGI_DATA,
    FCGI_PARAMS,
    FCGI_ABORT_REQUEST,
    ))


class ServerConnection(Connection):

    def __init__(self, *args, **kw):
        super(ServerConnection, self).__init__(*args, **kw)
        self.lock = Semaphore(1)

    def write_record(self, record):
        # We must serialize access for possible multiple request greenlets
        with self.lock:
            super(ServerConnection, self).write_record(record)


class ConnectionHandler(object):

    def __init__(self, conn, role, capabilities, request_handler):
        self.conn = conn
        self.role = role
        self.capabilities = capabilities
        self.request_handler = request_handler
        self.requests = {}
        self.keep_open = None
        self.closing = False

    def send_record(self, record_type, content='',
            request_id=FCGI_NULL_REQUEST_ID):
        self.conn.write_record(Record(record_type, content, request_id))

    def fcgi_begin_request(self, record):
        role, flags = begin_request_struct.unpack(record.content)
        if role != self.role:
            self.send_record(FCGI_END_REQUEST, end_request_struct.pack(
                0,  FCGI_UNKNOWN_ROLE), record.request_id)
            logger.error('Request role (%s) does not match server role (%s)',
                    role, self.role)
            self.event.set()
        else:
            # Should we check this for every request instead?
            if self.keep_open is None:
                self.keep_open = bool(FCGI_KEEP_CONN & flags)
            request = Request(self.conn, record.request_id, role)
            if role == FCGI_FILTER:
                request.data = InputStream()
            self.requests[request.id] = request

    def fcgi_params(self, record, request):
        if record.content:
            request.environ_list.append(record.content)
        else:
            request.environ.update(unpack_pairs(''.join(request.environ_list)))
            del request.environ_list
            if request.role == FCGI_AUTHORIZER:
                request.greenlet = spawn(self._handle_request, request)

    def fcgi_abort_request(self, record, request):
        greenlet = request.greenlet
        if not (greenlet is None or greenlet.ready()):
            request.greenlet.kill()
        if request.id in self.requests:
            del self.requests[request.id]
            self.event.set()
        logger.warn('Request %s aborted' % request.id)

    def fcgi_get_values(self, record):
        pairs = ((name, self.capabilities.get(name)) for name, _ in
                unpack_pairs(record.content))
        content = pack_pairs(
                (name, str(value)) for name, value in pairs if value)
        self.send_record(FCGI_GET_VALUES_RESULT, content)
        self.event.set()

    def run(self):
        self.event = Event()
        reader = spawn(self._reader)
        while 1:
            self.event.wait()
            logger.debug('Request handler finished its job')
            if self.requests or (self.keep_open and not reader.ready()):
                logger.debug(
                        'Connection left open due to remaining requests '
                        'or KEEP_CONN flag')
                self.event.clear()
            else:
                break
        logger.debug('Closing connection')
        self.conn.close()

    def _handle_request(self, request):
        try:
            self.request_handler(request)
            request.stdout.close()
            request.stderr.close()
        finally:
            self.send_record(FCGI_END_REQUEST, end_request_struct.pack(
                1, FCGI_REQUEST_COMPLETE), request.id)
            del self.requests[request.id]
            self.event.set()

    def _reader(self):
        for record in self.conn:
            if record.type in EXISTING_REQUEST_REC_TYPES:
                request = self.requests.get(record.request_id)
                if not request:
                    logger.error('%s for non-existent request' % record)
                elif record.type == FCGI_STDIN:
                    request.stdin.feed(record.content)
                    if record.content == '' and request.role == FCGI_RESPONDER:
                        request.greenlet = spawn(self._handle_request, request)
                elif record.type == FCGI_DATA:
                    request.data.feed(record.content)
                    if record.content == '' and request.role == FCGI_FILTER:
                        request.greenlet = spawn(self._handle_request, request)
                elif record.type == FCGI_PARAMS:
                    self.fcgi_params(record, request)
                elif record.type == FCGI_ABORT_REQUEST:
                    self.fcgi_abort_request(record, request)
            elif record.type == FCGI_BEGIN_REQUEST:
                self.fcgi_begin_request(record)
            elif record.type == FCGI_GET_VALUES:
                self.fcgi_get_values(record)
            else:
                logger.error('%s: Unknown record type' % record)
                self.send_record(FCGI_UNKNOWN_TYPE,
                        unknown_type_struct.pack(record.type))

        self.event.set()


class FastCGIServer(StreamServer):
    """
    Server that handles communication with Web-server via FastCGI protocol.
    It is request_handler's responsibility to choose protocol and deal with
    application invocation. gevent_fastcgi.wsgi module contains WSGI
    protocol implementation.
    """

    def __init__(self, bind_address, request_handler, role=FCGI_RESPONDER,
            num_workers=1, buffer_size=1024, max_conns=1024, **kwargs):
        if isinstance(bind_address, basestring):
            # StreamServer only accepts socket or tuple(address, port) so
            # we need to pre-cook UNIX-socket for it
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(bind_address)
            sock.listen(max_conns)
            bind_address = sock

        super(FastCGIServer, self).__init__(bind_address,
                self.handle_connection, spawn=max_conns, **kwargs)

        if role not in (FCGI_RESPONDER, FCGI_FILTER, FCGI_AUTHORIZER):
            raise ValueError('Illegal FastCGI role %s' % role)

        self.role = role
        self.request_handler = request_handler
        self.buffer_size = buffer_size
        self.capabilities = dict(
                FCGI_MAX_CONNS=str(max_conns),
                FCGI_MAX_REQS=str(max_conns * 1024),
                FCGI_MPXS_CONNS='1',
                )

        assert int(num_workers) >= 1, 'num_workers must be greate than zero'
        self.num_workers = int(num_workers)
        self.workers = []

    def start(self):
        if not self.started:
            if self.num_workers > 1:
                self.pre_start()
                for _ in range(self.num_workers):
                    pid = os.fork()
                    if pid:
                        # master process
                        self.workers.append(pid)
                    else:
                        # worker
                        del self.workers
                        exit = Event()
                        signal(SIGHUP, exit.set)
                        super(FastCGIServer, self).start()
                        while not exit.ready():
                            try:
                                exit.wait() # wait forever
                            finally:
                                os._exit(0)
                
                # this is used to indicate all workers are dead
                self._workers_dead = Event()

                # because we wont call StreamServer.start in master process
                self.started = True

                signal(SIGCHLD, self._child_died)
                signal(SIGHUP, self._kill_workers)
            else:
                return super(FastCGIServer, self).start()

    def kill(self):
        if hasattr(self, 'workers'):
            # master process
            if self.workers:
                self._kill_workers()
                self._workers_dead.wait()
            if self.socket.family == socket.AF_UNIX:
                # delete socket file
                try:
                    os.unlink(self.socket.getsockname())
                except OSError:
                    logger.exception('Failed to remove socket file')
            return super(FastCGIServer, self).kill()
        else:
            os._exit(0)

    def handle_connection(self, sock, addr):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            sock.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
        conn = ServerConnection(sock, self.buffer_size)
        handler = ConnectionHandler(conn, self.role, self.capabilities,
                self.request_handler)
        handler.run()

    def _kill_workers(self, signo=SIGHUP):
        for pid in self.workers:
            try:
                os.kill(pid, signo)
            except OSError, x:
                if x.errno == 3:
                    self.workers.remove(pid)
                elif x.errno == 10:
                    self.workers = []
                    self._workers_dead.set()
                    break

    def _child_died(self):
        for worker in tuple(self.workers):
            try:
                pid, status = os.waitpid(worker, os.WNOHANG)
            except OSError, x:
                if x.errno == errno.ECHILD:
                    self.workers.remove(worker)
                    continue
            else:
                if pid:
                    self.workers.remove(pid)

        if not self.workers:
            self._workers_dead.set()
