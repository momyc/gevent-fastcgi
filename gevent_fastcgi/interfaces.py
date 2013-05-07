# Copyright (c) 2011-2013, Alexander Kulakov
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from zope.interface import Interface, Attribute


class IConnection(Interface):

    def read_record():
        """
        Receive and deserialize next record from peer.
        Return None if no more records available
        """

    def write_record(record):
        """
        Serialize and send IRecord instance to peer
        """

    def close():
        """
        Close connection
        """


class IRequest(Interface):

    id = Attribute('ID')
    environ = Attribute('Request environment dict')
    stdin = Attribute('Standard input stream')
    stout = Attribute('Standard output stream')
    stderr = Attribute('Standard error stream')


class IRequestHandler(Interface):

    def __call__(request):
        """ Handle single request
        """
