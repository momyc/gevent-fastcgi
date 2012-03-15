#gevent-fastcgi

This is FastCGI/WSGI server implementation using gevent library.

## Installation

```bash
$ python setup.py install
```

## Usage

```python
from gevent_fastcgi import WSGIServer
from myapp import app

server = WSGIServer(('127.0.0.1', 4000), app, max_conns=1024)
server.serve_forever()
```
It also can be used as server for paster ini-scripts as following:

```
...
[server:main]
use = egg:gevent_fastcgi#fastcgi
host = 127.0.0.1
port = 4000
max_conns = 1024
...
```

