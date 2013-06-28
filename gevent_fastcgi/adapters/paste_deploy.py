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

from functools import wraps

import gevent.monkey
from paste.deploy.converters import asbool

from ..server import FastCGIServer


def server_params(app, conf, host='127.0.0.1', port=5000, socket=None,
                  **kwargs):
    address = (host, int(port)) if socket is None else socket
    for name in kwargs.keys():
        if name in ('max_conns', 'num_workers', 'buffer_size', 'backlog',
                    'socket_mode'):
            kwargs[name] = int(kwargs[name])
        elif name.startswith('gevent.monkey.') and asbool(kwargs.pop(name)):
            name = name[14:]
            if name in gevent.monkey.__all__:
                getattr(gevent.monkey, name)()
    return (app, address), kwargs


@wraps(server_params)
def fastcgi_server_runner(*args, **kwargs):
    (handler, address), kwargs = server_params(*args, **kwargs)
    FastCGIServer(address, handler, **kwargs).serve_forever()


@wraps(server_params)
def wsgiref_server_runner(*args, **kwargs):
    from ..wsgi import WSGIRefRequestHandler

    (app, address), kwargs = server_params(*args, **kwargs)
    handler = WSGIRefRequestHandler(app)
    FastCGIServer(address, handler, **kwargs).serve_forever()


@wraps(server_params)
def wsgi_server_runner(*args, **kwargs):
    from ..wsgi import WSGIRequestHandler

    (app, address), kwargs = server_params(*args, **kwargs)
    handler = WSGIRequestHandler(app)
    FastCGIServer(address, handler, **kwargs).serve_forever()
