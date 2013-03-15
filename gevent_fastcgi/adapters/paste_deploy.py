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

