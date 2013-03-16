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

import os
import re
from optparse import make_option
from django.core.management import BaseCommand, CommandError

__all__ = ['GeventFastCGI']

class Command(BaseCommand):
    args='<host:port>'
    help='Start gevent-fastcgi server'
    option_list = BaseCommand.option_list + (
        make_option('--maxconns', type='int', dest='max_conns', default=1024,
            metavar='MAX_CONNS', help='Maximum simulteneous connections (default %default)'),
        make_option('--daemon', action='store_true', dest='daemonize', default=False,
            help='Become a daemon'),
        make_option('--workdir', dest='our_home_dir', default='.', metavar='WORKDIR',
            help='Chande dir in daemon mode (default %default)'),
        make_option('--stdout', dest='out_log', metavar='STDOUT',
            help='stdout in daemon mode (default sys.devnull)'),
        make_option('--stderr', dest='err_log', metavar='STDERR',
            help='stderr in daemon mode (default sys.devnull)'),
        make_option('--umask', dest='umask', type='int', default=022, metavar='UMASK',
            help='umask in daemon mode (default 022)'),
    )

    def handle(self, *args, **options):
        from os.path import abspath, dirname, isdir
        from gevent_fastcgi.server import FastCGIServer
        from gevent_fastcgi.wsgi import WSGIRequestHandler
        from django.core.handlers.wsgi import WSGIHandler
        
        if not args:
            raise CommandError('bind address is not specified')

        if len(args) > 1:
            raise CommandError('unexpected arguments: %s', ' '.join(args[1:]))

        try:
            host, port = args[0].split(':', 1)
        except ValueError:
            address = abspath(args[0])
            if not isdir(dirname(address)):
                raise CommandError('directory %s does not exist', dirname(address))
        else:
            try:
                address = (host, int(port))
            except ValueError:
                raise CommandError('port must be an integer value')
        
        if options['daemonize']:
            from django.utils.daemonize import become_daemon

            daemon_opts = dict((key, value) for key, value in options.items() if key in
                    ('our_home_dir', 'out_log', 'err_log', 'umask'))
            become_daemon(**daemon_opts)

        for name in ('num_workers', 'max_conns', 'buffer_size'):
            if name in options:
                options[name] = int(options[name])

        app = WSGIHandler()
        request_handler = WSGIRequestHandler(app)
        server = FastCGIServer(address, request_handler, **options)
        server.serve_forever()

