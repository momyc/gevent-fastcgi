from random import random, randint
from gevent import socket, sleep


def dice():
    return bool(randint(0, 3))


def delay():
    sleep(random() / 27.31)


class MockSocket(object):

    def __init__(self, data=''):
        self.input = data
        self.output = ''
        self.fail = False

    def sendall(self, data):
        if self.fail:
            raise socket.error(32, 'Peer closed connection')
        self.output += data
        delay()

    def recv(self, max_len=0):
        if self.fail:
            raise socket.error(32, 'Peer closed connection')
        if not self.input:
            return ''
        if max_len <= 0:
            max_len = len(self.input)
        if not dice():
            max_len = randint(1, max_len)
        data = self.input[:max_len]
        self.input = self.input[max_len:]
        delay()
        return data

    def close(self):
        pass

    def setsockopt(self, *args):
        pass

    def feed(self, data):
        self.input += data

    def flip(self):
        self.input, self.output = self.output, ''
