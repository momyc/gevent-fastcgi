from __future__ import absolute_import

import os
import unittest
from paste.deploy import loadserver
import gevent

from .utils import WSGIApplication


app = WSGIApplication('Hello there!')
here = os.path.dirname(__file__)


class TestAdapters(unittest.TestCase):

    def test_paster_adapter(self):
        server = loadserver('config:test.ini', relative_to=here)

        g = gevent.spawn(server, app)
        gevent.sleep(2)
        g.kill()
        g.join()
