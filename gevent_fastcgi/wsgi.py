import sys
import logging
from traceback import format_exc
from types import StringType, ListType
from wsgiref.handlers import BaseCGIHandler
from wsgiref.headers import Headers

from zope.interface import implements

from gevent_fastcgi.interfaces import IRequestHandler
from gevent_fastcgi.const import *


MANDATORY_WSGI_ENVIRON_VARS = frozenset((
    'REQUEST_METHOD',
    'SCRIPT_NAME',
    'PATH_INFO',
    'QUERY_STRING',
    'CONTENT_TYPE',
    'CONTENT_LENGTH',
    'SERVER_NAME',
    'SERVER_PORT',
    'SERVER_PROTOCOL',
    ))


logger = logging.getLogger(__name__)


class WSGIRequestHandler(object):

    implements(IRequestHandler)

    def __init__(self, app):
        self.app = app

    def __call__(self, request):
        handler = BaseCGIHandler(request.stdin, request.stdout, request.stderr, request.environ)
        handler.run(self.app)
