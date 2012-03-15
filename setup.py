from setuptools import setup, find_packages
import re

__version__ = re.match(r'\s*__version__\s*=\s*\'(.*)\'', file('gevent_fastcgi.py').read()).group(1)

setup(name='gevent-fastcgi',
      version=__version__,
      description="FastCGI/WSGI server implementation based on gevent library",
      long_description='''FastCGI/WSGI server implemented using gevent library.
      Supports connection multiplexing. Compatibe with PasteDeploy.''',
      keywords='fastcgi gevent wsgi',
      author='Alexander Kulakov',
      author_email='a.kulakov@mail.ru',
      url='http://github.com/momyc/gevent-fastcgi',
      py_modules=['gevent_fastcgi'],
      zip_safe=True,
      license='MIT',
      install_requires=[
          "gevent>=0.13.6"
      ],
      entry_points="""
      [paste.server_runner]
      fastcgi=gevent_fastcgi:run_server
      """,
      test_suite="tests",
      )
