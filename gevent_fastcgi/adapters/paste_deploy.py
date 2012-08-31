import gevent.monkey
from paste.deploy.converters import asbool

from gevent_fastcgi.server import WSGIServer


def run_server(app, conf, host='127.0.0.1', port=5000, socket=None, **kwargs):    
    for name in kwargs.keys():
        if not name.startswith('gevent.monkey.'):
            continue
        if not asbool(kwargs.pop(name)):
            continue
        name = name[14:]
        if name in gevent.monkey.__all__:
            getattr(gevent.monkey, name)()

    addr = socket or (host, int(port))

    WSGIServer(addr, app, **kwargs).serve_forever()
