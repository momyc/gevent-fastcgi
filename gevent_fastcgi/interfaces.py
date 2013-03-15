from zope.interface import Interface, Attribute


class IConnection(Interface):

    def read_record():
        """ Receive and deserialize next record from peer. Return None if no more records available
        """

    def write_record(record):
        """ Serialize and send IRecord instance to peer
        """

    def close():
        """ Close connection
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

