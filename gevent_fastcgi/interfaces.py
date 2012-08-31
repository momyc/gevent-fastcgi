from zope.interface import Interface, Attribute


class IRecord(Interface):

    type = Attribute("Record type as defined in FastCGI spec")
    request_id = Attribute("ID of associated request or None")
    content = Attribute("Record payload specific to reacord type")


class IConnection(Interface):

    def read_record():
        """ Receive and deserialize next record from peer. Return None if no more records available
        """

    def write_records(record):
        """ Serialize and send IRecord instance to peer
        """

    def close():
        """ Close connection
        """

class IServer(Interface):

    role = Attribute("One of FCGI_RESPONDER, FCGI_FILTER, FCGI_AUTHENTICATOR")

    def app(environ, start_response):
        """ WSGI application
        """

    def capability(name):
        """ Return string value associeted with name or empty string.
        Used to generate FCGI_GET_VALUES_RESULT response.
        """
