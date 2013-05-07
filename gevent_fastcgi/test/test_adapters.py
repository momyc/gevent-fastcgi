from __future__ import absolute_import

import os
import unittest
from paste.deploy import loadserver, loadapp
import gevent

from .utils import WSGIApplication


class TestAdapters(unittest.TestCase):

    def test_paster_adapter(self):
        here = os.path.dirname(__file__)
        server = loadserver('config:test.ini', relative_to=here)
        app = WSGIApplication('Hello there!')

        g = gevent.spawn(server, app)
        gevent.sleep(2)
        g.kill()
        g.join()

