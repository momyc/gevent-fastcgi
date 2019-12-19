import os
import sys
from setuptools import setup, Extension, find_packages


ext_modules = []
# C speedups are no good for PyPy
if '__pypy__' not in sys.builtin_module_names:
    if os.name == "nt":
        ext_modules.append(
            Extension('gevent_fastcgi.speedups', ['gevent_fastcgi/speedups.c'], libraries=["Ws2_32"]))
    else:
        ext_modules.append(
            Extension('gevent_fastcgi.speedups', ['gevent_fastcgi/speedups.c']))

setup(
    name='gevent-fastcgi',
    version='1.1.0.0',
    description='''FastCGI/WSGI client and server implemented using gevent
    library''',
    long_description='''
    FastCGI/WSGI server implementation using gevent library. No need to
    monkeypatch and slow down your favourite FastCGI server in order to make
    it "green".

    Supports connection multiplexing. Out-of-the-box support for Django and
    frameworks that use PasteDeploy including Pylons and Pyramid.
    ''',
    keywords='fastcgi gevent wsgi',
    author='Alexander Kulakov',
    author_email='a.kulakov@mail.ru',
    url='http://github.com/momyc/gevent-fastcgi',
    packages=find_packages(exclude=('gevent_fastcgi.tests.*',)),
    zip_safe=True,
    license='MIT',
    install_requires=[
        "zope.interface>=3.8.0",
        "gevent>=0.13.6",
        "six",
    ],
    entry_points={
        'paste.server_runner': [
            'fastcgi = gevent_fastcgi.adapters.paste_deploy:fastcgi_server_runner',
            'wsgi = gevent_fastcgi.adapters.paste_deploy:wsgi_server_runner',
            'wsgiref = gevent_fastcgi.adapters.paste_deploy:wsgiref_server_runner',
        ],
    },
    classifiers=(
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Server',
    ),
    test_suite="tests",
    tests_require=['mock'],
    ext_modules=ext_modules
)
