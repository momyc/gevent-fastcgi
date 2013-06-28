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

from optparse import make_option
from django.core.management import BaseCommand, CommandError


class Command(BaseCommand):
    args = '<host>:<port> | <socket file>'
    help = 'Start gevent-fastcgi server'
    option_list = BaseCommand.option_list + (
        make_option('--max-conns', type='int', dest='max_conns', default=1024,
                    metavar='MAX_CONNS',
                    help='Maximum simulteneous connections (default %default)',
                    ),
        make_option('--buffer-size', type='int', dest='buffer_size',
                    default=4096, metavar='BUFFER_SIZE',
                    help='Read buffer size (default %default)',
                    ),
        make_option('--num-workers', type='int', dest='num_workers', default=1,
                    metavar='NUM_WORKERS',
                    help='Number of worker processes (default %default)',
                    ),
        make_option('--backlog', type='int', dest='backlog',
                    metavar='LISTEN_BACKLOG',
                    help='Listen backlog (default %default)',
                    ),
        make_option('--socket-mode', type='int', dest='socket_mode',
                    metavar='SOCKET_MODE',
                    help='Socket file mode',
                    ),
        make_option('--daemon', action='store_true', dest='daemonize',
                    default=False, help='Become a daemon'),
        make_option('--work-dir', dest='our_home_dir', default='.',
                    metavar='WORKDIR',
                    help='Chande dir in daemon mode (default %default)'),
        make_option('--stdout', dest='out_log', metavar='STDOUT',
                    help='stdout in daemon mode (default sys.devnull)'),
        make_option('--stderr', dest='err_log', metavar='STDERR',
                    help='stderr in daemon mode (default sys.devnull)'),
        make_option('--umask', dest='umask', type='int', default=022,
                    metavar='UMASK', help='umask in daemon mode (default 022)',
                    ),
    )

    def handle(self, *args, **options):
        from os.path import dirname, isdir
        from gevent_fastcgi.server import FastCGIServer
        from gevent_fastcgi.wsgi import WSGIRequestHandler
        from django.core.handlers.wsgi import WSGIHandler

        if not args:
            raise CommandError('Please specify binding address')

        if len(args) > 1:
            raise CommandError('Unexpected arguments: %s' % ' '.join(args[1:]))

        bind_address = args[0]

        try:
            host, port = bind_address.split(':', 1)
        except ValueError:
            socket_dir = dirname(bind_address)
            if not isdir(socket_dir):
                raise CommandError(
                    'Please create directory for socket file first %r' %
                    dirname(socket_dir))
        else:
            try:
                bind_address = (host, int(port))
            except ValueError:
                raise CommandError('Invalid binding address %r' % bind_address)

        if options['daemonize']:
            from django.utils.daemonize import become_daemon

            daemon_opts = dict(
                (key, value) for key, value in options.items() if key in (
                    'our_home_dir', 'out_log', 'err_log', 'umask'))
            become_daemon(**daemon_opts)

        kwargs = dict((
            (name, value) for name, value in options.iteritems() if name in (
                'num_workers', 'max_conns', 'buffer_size', 'backlog',
                'socket_mode')))

        app = WSGIHandler()
        request_handler = WSGIRequestHandler(app)
        server = FastCGIServer(bind_address, request_handler, **kwargs)
        server.serve_forever()
