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


MONKEY_PATCH_NAMES = ('os', 'socket', 'thread', 'select', 'time', 'ssl', 'all')


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
        make_option('--monkey-patch', dest='monkey_patch',
                    help='Comma separated list of function names from '
                    'gevent.monkey module. Allowed names are: ' + ', '.join(
                        map('"{0}"'.format, MONKEY_PATCH_NAMES))),
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
            port = int(port)
        except ValueError:
            socket_dir = dirname(bind_address)
            if not isdir(socket_dir):
                raise CommandError(
                    'Please create directory for socket file first %r' %
                    dirname(socket_dir))
        else:
            if options['socket_mode'] is not None:
                raise CommandError('--socket-mode option can only be used '
                                   'with Unix domain sockets. Either use '
                                   'socket file path as address or do not '
                                   'specify --socket-mode option')
            bind_address = (host, port)

        if options['monkey_patch']:
            names = filter(
                None, map(str.strip, options['monkey_patch'].split(',')))
            if names:
                module = __import__('gevent.monkey', fromlist=['*'])
                for name in names:
                    if name not in MONKEY_PATCH_NAMES:
                        raise CommandError(
                            'Unknown name "{0}" in --monkey-patch option'
                            .format(name))
                    patch_func = getattr(module, 'patch_{0}'.format(name))
                    patch_func()

        if options['daemonize']:
            from django.utils.daemonize import become_daemon

            daemon_opts = dict(
                (key, value) for key, value in options.items() if key in (
                    'our_home_dir', 'out_log', 'err_log', 'umask'))
            become_daemon(**daemon_opts)

        kwargs = dict((
            (name, value) for name, value in options.iteritems() if name in (
                'num_workers', 'max_conns', 'buffer_size', 'socket_mode')))

        app = WSGIHandler()
        request_handler = WSGIRequestHandler(app)
        server = FastCGIServer(bind_address, request_handler, **kwargs)
        server.serve_forever()
