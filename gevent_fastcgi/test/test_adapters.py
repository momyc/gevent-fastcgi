import unittest

from gevent import spawn, sleep


def plain_app(request):
    request.stdout.write('\r\n'.join((
        'Status: 200 OK',
        '',
        'Hello World!',
        )))


class TestAdapters(unittest.TestCase):

    def test_paster_adapter(self):
        from gevent_fastcgi.const import FCGI_GET_VALUES, FCGI_GET_VALUES_RESULT
        from gevent_fastcgi.base import Record
        from gevent_fastcgi.test.utils import make_connection, WSGIApplication

        app = WSGIApplication(response='Hello World!')
        server = self._spawn_server(app, host='127.0.0.1', port='3928')
        try:
            sleep(2)
            with make_connection(('127.0.0.1', 3928)) as conn:
                conn.write_record(Record(FCGI_GET_VALUES))
                done = False
                for record in conn:
                    self.assertFalse(done)
                    self.assertEquals(record.type, FCGI_GET_VALUES_RESULT)
                    done = True
        finally:
            server.kill()

    def test_paster_adapter_plain_app(self):
        from gevent_fastcgi.const import FCGI_BEGIN_REQUEST, FCGI_END_REQUEST, FCGI_STDIN, FCGI_PARAMS, FCGI_STDOUT, FCGI_STDERR, FCGI_RESPONDER
        from gevent_fastcgi.base import Record, begin_request_struct
        from gevent_fastcgi.test.utils import make_connection, pack_env

        server = self._spawn_server(plain_app, host='127.0.0.1', port='3928', plain_fastcgi='yes')
        try:
            sleep(2)
            with make_connection(('127.0.0.1', 3928)) as conn:
                map(conn.write_record, (
                    Record(FCGI_BEGIN_REQUEST, begin_request_struct.pack(FCGI_RESPONDER, 0), 1),
                    Record(FCGI_PARAMS, pack_env(REQUEST_METHOD='GET'), 1),
                    Record(FCGI_PARAMS, '', 1),
                    Record(FCGI_STDIN, '', 1),
                    ))
                done = False
                stdout = ''
                for record in conn:
                    self.assertFalse(done)
                    self.assertEquals(record.request_id, 1)
                    if record.type == FCGI_END_REQUEST:
                        done = True
                    elif record.type == FCGI_STDOUT:
                        stdout += record.content
                    elif record.type == FCGI_STDERR:
                        self.assertFalse(record.content)
                    else:
                        self.fail('Unexpected record received from server %r' % record)
                self.assertTrue(stdout.startswith('Status: 200 OK\r\n'))
        finally:
            server.kill()

    def _spawn_server(self, app, **kw):
        from gevent_fastcgi.adapters.paste_deploy import wsgi_server

        for k,v in (
            ('max_conns', '2048'),
            ('buffer_size', '512'),
            ('num_workers', '2'),
            ('gevent.monkey.patch_thread', 'yes'),
            ):
            kw.setdefault(k, v)

        return spawn(wsgi_server, app, {}, **kw)
        
