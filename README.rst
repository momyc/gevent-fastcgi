gevent-fastcgi
==============

`FastCGI <http://fastcgi.com/>`_ server implementation using `gevent <http://gevent.org/>`_ coroutine-based networking library.
No need to monkeypatch and slow down your favourite FastCGI server in order to make it "green".

Provides simple request handler API to allow for custom request handlers.
Comes with two WSGI request hadler implementations -- one using standard *wsgiref.handlers.BasicCGIHandler* and another using original request handler.

Full support for FastCGI protocol connection multiplexing
feature.

Can fork multiple processes to better utilize multi-core CPUs.

Includes adapters for `Django <http://djangoproject.com/>`_ and frameworks that use 
`PasteDeploy <http://pythonpaste.org/deploy>`_ like `Pylons / Pyramid <http://pylonsproject.org/>`_ and `TurboGears <http://turbogears.org/>`_ to simplify depolyment.

Contributors
------------

This project could not be where it is now without help of the following great people:

        * `David Galeano <https://github.com/davidgaleano>`_
        * `Lucas Clemente Vella <https://github.com/lvella>`_
        * `Peter D. Gray <https://github.com/peter-conalgo>`_

Thank you guys for all your help!

Installation
------------

To install gevent-fastcgi using pip run the following command:

.. code:: bash

        $ pip install gevent-fastcgi

If you prefer easy_install here is how to use it:

.. code:: bash

        $ easy_install gevent-fastcgi


Usage
-----

This is how to use gevent-fastcgi in stand-alone mode:

.. code:: python

        from gevent_fastcgi.server import FastCGIServer
        from gevent_fastcgi.wsgi import WSGIRequestHandler


        def wsgi_app(environ, start_response):
            start_response('200 OK', [('Content-type', 'text/plain')])
            yield 'Hello World!'


        request_handler = WSGIRequestHandler(wsgi_app)
        server = FastCGIServer(('127.0.0.1', 4000), request_handler, num_workers=4)
        server.serve_forever()


Using with PasteDeploy_ and friends
-----------------------------------

Gevent-fastcgi defines three *paste.server_runner* entry points. Each of them will run FastCGIServer with different request
handler implementation:

*wsgi*
        *gevent_fastcgi.wsgi.WSGIRequestHandler* will be used to handle requests.
        Application is expected to be a WSGI-application.

*wsgiref*
        *gevent_fastcgi.wsgi.WSGIRefRequestHandler* which uses standard 
        *wsgiref.handlers* will be used to handle requests.
        Application is expected to be a WSGI-application.

*fastcgi*
        Application is expected to implement *gevent_fastcgi.interfaces.IRequestHandler*
        interface. It should use *request.stdin* to receive request body and
        *request.stdout* and/or *request.stderr* to send response back to Web-server.

Use it as following:

.. code:: ini

        [server:main]
        use = egg:gevent_fastcgi#wsgi
        host = 127.0.0.1
        port = 4000
        # UNIX domain socket can be used by specifying path instead of host and port
        # socket = /path/to/socket
        # socket_mode = 0660

        # The following values are used in reply to Web-server on `FCGI_GET_VALUES` request
        #
        # Maximum allowed simulteneous connections, i.e. the size of greenlet pool
        # used for connection handlers.
        max_conns = 1024
        max_reqs = 1024

        # Fork `num_workers` child processes after socket is bound.
        # Must be equal or greate than 1. No children will be forked
        # if set to 1 or not specified
        num_workers = 8

        # Call specified functions of gevent.monkey module before starting the server
        gevent.monkey.patch_thread = yes
        gevent.monkey.patch_time = no
        gevent.monkey.patch_socket = on
        gevent.monkey.patch_ssl = off
        # or
        gevent.monkey.patch_all = yes


`Django <http://djangoproject.com/>`_ adapter
---------------------------------------------

Add *gevent_fastcgi.adapters.django* to INSTALLED_APPS of settings.py then run
the following command (replace <address> with <host>:<port> or <unix-socket>):

.. code:: bash

        $ python manage.py run_gevent_fastcgi <address>


Custom request handlers
-----------------------

Starting from version 0.1.16dev It is possible to use custom request handler with *gevent_fastcgi.server.FastCGIServer*. Such a handler should implement
*gevent_fastcgi.interfaces.IRequestHandler* interface and basically is just a callable that accepts single positional argument *request*. *gevent_fastcgi.wsgi* module contains two implementations of *IRequestHandler*. 

Request handler is run in separate greenlet. Request argument passed to request
handler callable has the following attributes:

*environ*
        Dictionary containing request environment.
        NOTE: contains whatever was sent by Web-server via FCGI_PARAM stream

*stdin*
        File-like object that represents request body, possibly empty

*stdout*
        File-like object that should be used by request handler to send response (including response headers)

*stderr*
        File-like object that can be used to send error information back to Web-server

Following is sample of custom request handler implementation:

.. code:: python

        import os
        from zope.interface import implements
        from gevent import spawn, joinall
        from gevent_subprocess import Popen, PIPE
        from gevent_fastcgi.interfaces import IRequestHandler


        # WARNING!!!
        # CGIRequestHandler is for demonstration purposes only!!!
        # IT MUST NOT BE USED IN PRODUCTION ENVIRONMENT!!!

        class CGIRequestHandler(object):

            implements(IRequestHandler)

            def __init__(self, root, buf_size=1024):
                self.root = os.path.abspath(root)
                self.buf_size = buf_size

            def __call__(self, request):
                script_name = request.environ['SCRIPT_NAME']
                if script_name.startswith('/'):
                    script_name = script_name[1:]
                    script_filename = os.path.join(self.root, script_name)

                if script_filename.startswith(self.root) and
                os.path.isfile(script_filename) and
                os.access(script_filename, os.X_OK):
                    proc = Popen(script_filename, stdin=PIPE, stdout=PIPE, stderr=PIPE)
                    joinall((spawn(self.copy_stream, src, dest) for src, dest in [
                        (request.stdin, proc.stdin),
                        (proc.stdout, request.stdout),
                        (proc.stderr, request.stderr),
                    ]))
                else:
                    # report an error
                    request.stderr.write('Cannot locate or execute CGI-script %s' % script_filename)

                    # and send a reply
                    request.stdout.write('\r\n'.join((
                        'Status: 404 Not Found',
                        'Content-Type: text/plain',
                        '',
                        'No resource can be found for URI %s' % request.environ['REQUEST_URI'],
                    )))

            def copy_stream(self, src, dest):
                buf_size = self.buf_size
                read = src.read
                write = dest.write

                while True:
                    buf = read(buf_size)
                    if not buf:
                        break
                    write(buf)


        if __name__ == '__main__':
            from gevent_fastcgi.server import FastCGIServer

            address = ('127.0.0.1', 8000)
            handler = CGIRequestHandler('/var/www/cgi-bin')
            server = FastCGIServer(address, handler)
            server.serve_forever()
