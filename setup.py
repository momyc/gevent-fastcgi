from setuptools import setup, Extension, find_packages


setup(
    name='gevent-fastcgi',
    version='0.1.9dev',
    description='FastCGI/WSGI client and server implemented using gevent library',
    long_description='''
    FastCGI/WSGI server implementation using gevent library. No need to monkeypatch and
    slow down your favourite FastCGI server in order to make it "green".

    Supports connection multiplexing. Out-of-the-box support for Django and frameworks
    that use PasteDeploy including Pylons and Pyramid.
    ''',
    keywords='fastcgi gevent wsgi',
    author='Alexander Kulakov',
    author_email='a.kulakov@mail.ru',
    url='http://github.com/momyc/gevent-fastcgi',
    packages=find_packages(exclude=('gevent_fastcgi.tests.*',)),
    zip_safe=True,
    license='MIT',
    install_requires=[
        "gevent>=0.13.6"
    ],
    entry_points={
       'paste.server_runner': ['fastcgi = gevent_fastcgi.server:run_server'],
    },
    test_suite="gevent_fastcgi.test",
    ext_modules=[Extension('gevent_fastcgi.speedups', ['gevent_fastcgi/speedups.c'])],
)
