#gevent-fastcgi

FastCGI/WSGI server implementation using gevent library. No need to monkeypatch and slow down your favourite FastCGI server in order to make it "green".

Supports connection multiplexing. Out-of-the-box support for Django and frameworks that use PasteDeploy including Pylons and Pyramid.

## Installation

```bash
$ python setup.py install
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
# path = /path/to/socket
max_conns = 1024
...
```
### Django

Add "gevent_fastcgi.adapters.django" to INSTALLED_APPS of settings.py then run the following command (replace host:port with desired values)
```
python manage.py run_gevent_fastcgi host:port
```
