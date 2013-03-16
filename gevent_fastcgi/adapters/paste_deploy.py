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
#    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#    THE SOFTWARE.

import gevent.monkey
from paste.deploy.converters import asbool

from gevent_fastcgi.server import FastCGIServer
from gevent_fastcgi.wsgi import WSGIRequestHandler


def wsgi_server(app, conf, host='127.0.0.1', port=5000, socket=None, plain_fastcgi=False, **kwargs):
    for name in kwargs.keys():
        if name in ('max_conns', 'num_workers', 'buffer_size'):
            kwargs[name] = int(kwargs[name])
        elif name.startswith('gevent.monkey.') and asbool(kwargs.pop(name)):
            name = name[14:]
            if name in gevent.monkey.__all__:
                getattr(gevent.monkey, name)()

    addr = socket or (host, int(port))
    if plain_fastcgi:
        request_handler = app
    else:
        request_handler = WSGIRequestHandler(app)
    FastCGIServer(addr, request_handler, **kwargs).serve_forever()

