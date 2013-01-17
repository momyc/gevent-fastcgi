#gevent-fastcgi

WSGI-over-FastCGI server implementation using `gevent <http://www.gevent.org/>`_ coroutine-based network  library.
No need to monkeypatch and slow down your favourite FastCGI server in order to make it "green".

Supports connection multiplexing. Includes adapters for Django and frameworks that use PasteDeploy like Pylons and Pyramid.

## Installation

```
$ pip install gevent-fastcgi
```
or
```
$ easy_install gevent-fastcgi
```

## Usage

```python
from gevent_fastcgi.server import WSGIServer
from myapp import app

server = WSGIServer(('127.0.0.1', 4000), app, max_conns=1024)
# To use UNIX-socket instead of TCP
# server = WSGIServer('/path/to/socket', app, max_conns=1024, max_reqs=1024 * 1024)

server.serve_forever()
```
### PasteDeploy

Gevent-fastcgi defines paste.server_runner entry point. Use it as following:
```
...
[server:main]
use = egg:gevent_fastcgi#fastcgi
host = 127.0.0.1
port = 4000
# Unix-socket can be used by specifying path instead of host and port
# socket = /path/to/socket

# The following values are used in reply to Web-server on `FCGI_GET_VALUES` request
#
# Maximum allowed simulteneous connections, i.e. the size of greenlet pool used for connection handlers.
max_conns = 1024
#
# Does not limit anything on FastCGI server side. Just a clue to Web-server on how many simulteneous requests
# can be handled by FastCGI server. This can be much higher than `max_conns` thanks to FastCGI connection multiplexing
max_reqs = 1024000

# Fork up to `num_workers` child processes after socket is bound.
# Must be equal or greate than 1. No children will be actually forked if set to 1 or omitted.
num_workers = 4

# Call specified functions of gevent.monkey module before starting the server
#gevent.monkey.patch_os = yes
#gevent.monkey.patch_thread = yes
#gevent.monkey.patch_time = yes
#gevent.monkey.patch_socket = yes
#gevent.monkey.patch_ssl = yes
# or
#gevent.monkey.patch_all = yes
...
```
### Django

Add "gevent_fastcgi.adapters.django" to INSTALLED_APPS of settings.py then run the following command (replace host:port with desired values)
```
python manage.py run_gevent_fastcgi host:port
```
