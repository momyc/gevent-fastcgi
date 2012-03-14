# Copyright (c) 2011 Alexander Kulakov <a.kulakov@mail.ru>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#
# $Id$

import unittest
import gevent
from gevent_fastcgi import *
from struct import pack, unpack

ADDR = ('127.0.0.1', 6000)
TEST_DATA = 'abc' * 4096

import logging
# logging.basicConfig(level=logging.DEBUG)

def app(environ, start_response):
    headers = [
        ('Content-type', environ['CONTENT_TYPE']),
        ('Content-length', environ['CONTENT_LENGTH']),
        ]
    start_response('200 OK', headers)
    return environ['wsgi.input']

class TestFastCGI(unittest.TestCase):
    def setUp(self):
        self.server = WSGIServer(ADDR, app)
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def test_1_values(self):
        conn = ClientConnection(ADDR)
        conn.send_get_values()
        resp_type, req_id, content = conn.read_record()
        self.assertEqual(resp_type, FCGI_GET_VALUES_RESULT)
        self.assertEqual(req_id, FCGI_NULL_REQUEST_ID)
        values = dict(unpack_pairs(content))

    def test_2_responder(self):
        name = 'World'
        conn = ClientConnection(ADDR)
        req_id = 123
        conn.send_begin_request(req_id=req_id)
        conn.send_params([
            ('SCRIPT_NAME', '/'),
            ('PATH_INFO', '/%s' % name),
            ('REQUEST_METHOD', 'POST'),
            ('CONTENT_TYPE', 'application/octet-stream'),
            ('CONTENT_LENGTH', str(len(TEST_DATA))),
            ], req_id=req_id)
        conn.send_params(req_id=req_id)
        conn.send_stdin(TEST_DATA, req_id=req_id)
        conn.send_stdin(req_id=req_id)
        while True:
            rec_type, resp_id, content = conn.read_record()
            self.assertEqual(req_id, resp_id)
            self.assertIn(rec_type, (FCGI_STDOUT, FCGI_STDERR, FCGI_END_REQUEST))
            if rec_type == FCGI_STDERR:
                self.assertEqual(content, '')
            elif rec_type == FCGI_STDOUT:
                pass
            elif rec_type == FCGI_END_REQUEST:
                app_status, req_status = conn.unpack_end_request(content)
                self.assertEqual(app_status, 0)
                self.assertEqual(req_status, FCGI_REQUEST_COMPLETE)
                break

