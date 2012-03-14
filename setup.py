from setuptools import setup, find_packages
import sys, os
from gevent_fastcgi import __version__, __doc__

setup(name='gevent-fastcgi',
      version=__version__,
      description="FastCGI/WSGI server implementation based on gevent library",
      long_description=__doc__,
      keywords='fastcgi gevent',
      author='Alexander Kulakov',
      author_email='a.kulakov@mail.ru',
      url='http://github.com/momyc/gevent-fastcgi',
      py_modules=['gevent_fastcgi'],
      zip_safe=True,
      install_requires=[
          "gevent>=0.13.6"
      ],
      entry_points="""
      [paste.server_runner]
      fastcgi=gevent_fastcgi:run_server
      # -*- Entry points: -*-
      """,
      test_suite="tests",
      )
