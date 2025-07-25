"""Stubs for patching HTTP and HTTPS requests"""

import logging
from http.client import HTTPConnection, HTTPResponse, HTTPSConnection
from io import BytesIO

from vcrmartin.errors import CannotOverwriteExistingCassetteException
from vcrmartin.record_mode import RecordMode
from vcrmartin.request import Request

from . import compat

from vcrmartin.constants import current_cassette

log = logging.getLogger(__name__)

class VCRFakeSocket:
    """
    A socket that doesn't do anything!
    Used when playing back cassettes, when there
    is no actual open socket.
    """

    def close(self):
        pass

    def settimeout(self, *args, **kwargs):
        pass

    def fileno(self):
        """
        This is kinda crappy.  requests will watch
        this descriptor and make sure it's not closed.
        Return file descriptor 0 since that's stdin.
        """
        return 0  # wonder how bad this is....


def parse_headers(header_list):
    """
    Convert headers from our serialized dict with lists for keys to a
    HTTPMessage
    """
    header_string = b""
    for key, values in header_list.items():
        for v in values:
            header_string += key.encode("utf-8") + b":" + v.encode("utf-8") + b"\r\n"
    return compat.get_httpmessage(header_string)


def serialize_headers(response):
    headers = response.headers if response.msg is None else response.msg
    out = {}
    for key, values in compat.get_headers(headers):
        out.setdefault(key, [])
        out[key].extend(values)
    return out


class VCRHTTPResponse(HTTPResponse):
    """
    Stub response class that gets returned instead of a HTTPResponse
    """

    def __init__(self, recorded_response):
        self.fp = None
        self.recorded_response = recorded_response
        self.reason = recorded_response["status"]["message"]
        self.status = self.code = recorded_response["status"]["code"]
        self.version = None
        self.version_string = None
        self._content = BytesIO(self.recorded_response["body"]["string"])
        self._closed = False
        self._original_response = self  # for requests.session.Session cookie extraction

        headers = self.recorded_response["headers"]
        # Since we are loading a response that has already been serialized, our
        # response is no longer chunked.  That means we don't want any
        # libraries trying to process a chunked response.  By removing the
        # transfer-encoding: chunked header, this should cause the downstream
        # libraries to process this as a non-chunked response.
        te_key = [h for h in headers.keys() if h.upper() == "TRANSFER-ENCODING"]
        if te_key:
            del headers[te_key[0]]
        self.headers = self.msg = parse_headers(headers)

        self.length = compat.get_header(self.msg, "content-length") or None

    @property
    def closed(self):
        # in python3, I can't change the value of self.closed.  So I'
        # twiddling self._closed and using this property to shadow the real
        # self.closed from the superclass
        return self._closed

    def read(self, *args, **kwargs):
        return self._content.read(*args, **kwargs)

    def read1(self, *args, **kwargs):
        return self._content.read1(*args, **kwargs)

    def readall(self):
        return self._content.readall()

    def readinto(self, *args, **kwargs):
        return self._content.readinto(*args, **kwargs)

    def readline(self, *args, **kwargs):
        return self._content.readline(*args, **kwargs)

    def readlines(self, *args, **kwargs):
        return self._content.readlines(*args, **kwargs)

    def seekable(self):
        return self._content.seekable()

    def tell(self):
        return self._content.tell()

    def isatty(self):
        return self._content.isatty()

    def seek(self, *args, **kwargs):
        return self._content.seek(*args, **kwargs)

    def close(self):
        self._closed = True
        return True

    def getcode(self):
        return self.status

    def isclosed(self):
        return self.closed

    def info(self):
        return parse_headers(self.recorded_response["headers"])

    def getheaders(self):
        message = parse_headers(self.recorded_response["headers"])
        return list(compat.get_header_items(message))

    def getheader(self, header, default=None):
        values = [v for (k, v) in self.getheaders() if k.lower() == header.lower()]

        if values:
            return ", ".join(values)
        else:
            return default

    def readable(self):
        return self._content.readable()

    @property
    def length_remaining(self):
        return self._content.getbuffer().nbytes - self._content.tell()

    def get_redirect_location(self):
        """
        Returns (a) redirect location string if we got a redirect
        status code and valid location, (b) None if redirect status and
        no location, (c) False if not a redirect status code.
        See https://urllib3.readthedocs.io/en/stable/reference/urllib3.response.html .
        """
        if not (300 <= self.status <= 399):
            return False
        return self.getheader("Location")

    @property
    def data(self):
        return self._content.getbuffer().tobytes()

    def drain_conn(self):
        pass

    def stream(self, amt=65536, decode_content=None):
        while True:
            b = self._content.read(amt)
            yield b
            if not b:
                break

def _with_cassette(func):
    def wrapper(self, *args, **kwargs):
        if self.cassette:
            return func(self, *args, **kwargs)
        else:
            return getattr(self.real_connection, func.__name__)(*args, **kwargs)
    return wrapper

class VCRConnection:
    # A reference to the cassette that's currently being patched in

    @property
    def cassette(self):
        try:
            return current_cassette.get()
        except LookupError:
            return None

    def _port_postfix(self):
        """
        Returns empty string for the default port and ':port' otherwise
        """
        port = (
            self.real_connection.port
            if not self.real_connection._tunnel_host
            else self.real_connection._tunnel_port
        )
        default_port = {"https": 443, "http": 80}[self._protocol]
        return f":{port}" if port != default_port else ""

    def _real_host(self):
        """Returns the request host"""
        if self.real_connection._tunnel_host:
            # The real connection is to an HTTPS proxy
            return self.real_connection._tunnel_host
        else:
            return self.real_connection.host

    def _uri(self, url):
        """Returns request absolute URI"""
        if url and not url.startswith("/"):
            # Then this must be a proxy request.
            return url
        uri = f"{self._protocol}://{self._real_host()}{self._port_postfix()}{url}"
        log.debug("Absolute URI: %s", uri)
        return uri

    def _url(self, uri):
        """Returns request selector url from absolute URI"""
        prefix = f"{self._protocol}://{self._real_host()}{self._port_postfix()}"
        return uri.replace(prefix, "", 1)

    @_with_cassette
    def request(self, method, url, body=None, headers=None, *args, **kwargs):
        """Persist the request metadata in self._vcr_request"""

        cassette = self.cassette

        if not cassette:
            return self.real_connection.request(method, url, body, headers, *args, **kwargs)

        self._vcr_request = Request(method=method, uri=self._uri(url), body=body, headers=headers or {})
        log.debug(f"Got {self._vcr_request}")

        if cassette.record_mode == RecordMode.ALL:
            #Here we know that we won't have to replay the request, so we can just send it to the real connection
            self.real_connection.request(method, url, body, headers, *args, **kwargs)
        else:
            # Note: The request may not actually be finished at this point, so
            # I'm not sending the actual request until getresponse().  This
            # allows me to compare the entire length of the response to see if it
            # exists in the cassette.

            self._sock = VCRFakeSocket()

    @_with_cassette
    def putrequest(self, method, url, *args, **kwargs):
        """
        httplib gives you more than one way to do it.  This is a way
        to start building up a request.  Usually followed by a bunch
        of putheader() calls.
        """
        cassette = self.cassette

        if not cassette:
            return self.real_connection.putrequest(method, url, *args, **kwargs)

        if not self._vcr_request:
            self._vcr_request = Request(method=method, uri=self._uri(url), body="", headers={})
            log.debug(f"Got {self._vcr_request}")
        
        if cassette.record_mode == RecordMode.ALL:
            self.real_connection.putrequest(method, url, *args, **kwargs)

    @_with_cassette
    def putheader(self, header, *values):
        cassette = self.cassette

        if not cassette:
            return self.real_connection.putheader(header, *values)

        self._vcr_request.headers[header] = values

        if cassette.record_mode == RecordMode.ALL:
            self.real_connection.putheader(header, *values)

    @_with_cassette
    def send(self, data):
        """
        This method is called after request(), to add additional data to the
        body of the request.  So if that happens, let's just append the data
        onto the most recent request in the cassette.
        """
        cassette = self.cassette

        if not cassette:
            return self.real_connection.send(data)

        self._vcr_request.body = self._vcr_request.body + data if self._vcr_request.body else data

        if cassette.record_mode == RecordMode.ALL:
            self.real_connection.send(data)

    @_with_cassette
    def close(self):
        # Note: the real connection will only close if it's open, so
        # no need to check that here.
        cassette = self.cassette

        if not cassette:
            return self.real_connection.close()

        self.real_connection.close()

    @_with_cassette
    def endheaders(self, message_body=None):
        """
        Normally, this would actually send the request to the server.
        We are not sending the request until getting the response,
        so bypass this part and just append the message body, if any.
        """
        cassette = self.cassette

        if not cassette:
            return self.real_connection.endheaders(message_body)

        if message_body is not None:
            self._vcr_request.body = message_body

        if cassette.record_mode == RecordMode.ALL:
            self.real_connection.endheaders(message_body)

    @_with_cassette
    def getresponse(self, _=False, **kwargs):
        """Retrieve the response"""
        # Check to see if the cassette has a response for this request. If so,
        # then return it

        cassette = self.cassette

        if not self.cassette:
            return self.real_connection.getresponse(_=False, **kwargs)

        if self.cassette.can_play_response_for(self._vcr_request):
            log.info(f"Playing response for {self._vcr_request} from cassette")
            response = self.cassette.play_response(self._vcr_request)
            return VCRHTTPResponse(response)
        else:
            if self.cassette.write_protected and self.cassette.filter_request(self._vcr_request):
                raise CannotOverwriteExistingCassetteException(
                    cassette=self.cassette,
                    failed_request=self._vcr_request,
                )

            # Otherwise, we should send the request, then get the response
            # and return it.

            log.info(f"{self._vcr_request} not in cassette, sending to real server")
            
            if not cassette.record_mode == RecordMode.ALL:
                #We've already executed the request if we're in record mode ALL, so we can just get the response
                self.real_connection.request(
                    method=self._vcr_request.method,
                    url=self._url(self._vcr_request.uri),
                    body=self._vcr_request.body,
                    headers=self._vcr_request.headers,
                )

            # get the response
            response = self.real_connection.getresponse()
            response_data = response.data if hasattr(response, "data") else response.read()

            # put the response into the cassette
            response = {
                "status": {"code": response.status, "message": response.reason},
                "headers": serialize_headers(response),
                "body": {"string": response_data},
            }
            self.cassette.append(self._vcr_request, response)
        return VCRHTTPResponse(response)

    def set_debuglevel(self, *args, **kwargs):
        self.real_connection.set_debuglevel(*args, **kwargs)

    @_with_cassette
    def connect(self, *args, **kwargs):
        """
        httplib2 uses this.  Connects to the server I'm assuming.

        Only pass to the baseclass if we don't have a recorded response
        and are not write-protected.
        """
        cassette = self.cassette

        if not cassette:
            return self.real_connection.connect(*args, **kwargs)

        if hasattr(self, "_vcr_request") and self.cassette and self.cassette.can_play_response_for(self._vcr_request):
            # We already have a response we are going to play, don't
            # actually connect
            return

        if self.cassette and self.cassette.write_protected:
            # Cassette is write-protected, don't actually connect
            return

        return self.real_connection.connect(*args, **kwargs)

        self._sock = VCRFakeSocket()

    @property
    def sock(self):
        if self.real_connection.sock:
            return self.real_connection.sock
        return self._sock

    @sock.setter
    def sock(self, value):
        if self.real_connection.sock:
            self.real_connection.sock = value

    def __init__(self, *args, **kwargs):
        kwargs.pop("strict", None)  # apparently this is gone in py3

        self.real_connection = self._baseclass(*args, **kwargs)

        self._sock = None

    def __setattr__(self, name, value):
        """
        We need to define this because any attributes that are set on the
        VCRConnection need to be propagated to the real connection.

        For example, urllib3 will set certain attributes on the connection,
        such as 'ssl_version'. These attributes need to get set on the real
        connection to have the correct and expected behavior.

        TODO: Separately setting the attribute on the two instances is not
        ideal. We should switch to a proxying implementation.
        """
        try:
            setattr(self.real_connection, name, value)
        except AttributeError:
            # raised if real_connection has not been set yet, such as when
            # we're setting the real_connection itself for the first time
            pass

        super().__setattr__(name, value)

    def __getattr__(self, name):
        """
        Send requests for weird attributes up to the real connection
        (counterpart to __setattr above)
        """
        if self.__dict__.get("real_connection"):
            # check in case real_connection has not been set yet, such as when
            # we're setting the real_connection itself for the first time
            return getattr(self.real_connection, name)

        return super().__getattr__(name)


for k, v in HTTPConnection.__dict__.items():
    if isinstance(v, staticmethod):
        setattr(VCRConnection, k, v)


class VCRHTTPConnection(VCRConnection):
    """A Mocked class for HTTP requests"""

    _baseclass = HTTPConnection
    _protocol = "http"
    debuglevel = _baseclass.debuglevel
    _http_vsn = _baseclass._http_vsn


class VCRHTTPSConnection(VCRConnection):
    """A Mocked class for HTTPS requests"""

    _baseclass = HTTPSConnection
    _protocol = "https"
    is_verified = True
    debuglevel = _baseclass.debuglevel
    _http_vsn = _baseclass._http_vsn
