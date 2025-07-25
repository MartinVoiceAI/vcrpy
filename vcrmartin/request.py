import logging
from typing import Dict
import warnings
from io import BytesIO
from urllib.parse import parse_qsl, urlparse

from .util import CaseInsensitiveDict, _is_nonsequence_iterator

log = logging.getLogger(__name__)


class MongoRequest:

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

class Request:
    """
    VCR's representation of a request.
    """

    def __init__(self, method, uri, body, headers):
        self.method = method
        self.uri = uri
        self._was_file = hasattr(body, "read")
        self._was_iter = _is_nonsequence_iterator(body)
        if self._was_file:
            self.body = body.read()
        elif self._was_iter:
            self.body = list(body)
        else:
            self.body = body
        self.headers = headers
        log.debug("Invoking Request %s", self.uri)

    @property
    def uri(self):
        return self._uri

    @uri.setter
    def uri(self, uri):
        self._uri = uri
        self.parsed_uri = urlparse(uri)

    @property
    def headers(self):
        return self._headers

    @headers.setter
    def headers(self, value):
        if not isinstance(value, HeadersDict):
            value = HeadersDict(value)
        self._headers = value

    @property
    def body(self):
        if self._was_file:
            return BytesIO(self._body)
        if self._was_iter:
            return iter(self._body)
        return self._body

    @body.setter
    def body(self, value):
        if isinstance(value, str):
            value = value.encode("utf-8")
        self._body = value

    def add_header(self, key, value):
        warnings.warn(
            "Request.add_header is deprecated. Please assign to request.headers instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.headers[key] = value

    @property
    def scheme(self):
        return self.parsed_uri.scheme

    @property
    def host(self):
        return self.parsed_uri.hostname

    @property
    def port(self):
        port = self.parsed_uri.port
        if port is None:
            try:
                port = {"https": 443, "http": 80}[self.parsed_uri.scheme]
            except KeyError:
                pass
        return port

    @property
    def path(self):
        return self.parsed_uri.path

    @property
    def query(self):
        q = self.parsed_uri.query
        return sorted(parse_qsl(q))

    # alias for backwards compatibility
    @property
    def url(self):
        return self.uri

    # alias for backwards compatibility
    @property
    def protocol(self):
        return self.scheme

    def __str__(self):
        return f"<Request ({self.method}) {self.uri}>"

    def __repr__(self):
        return self.__str__()

    def _to_dict(self):
        return {
            "method": self.method,
            "uri": self.uri,
            "body": self.body,
            "headers": {k: [v] for k, v in self.headers.items()},
        }

    @classmethod
    def _from_dict(cls, dct):
        return Request(**dct)


class HeadersDict(CaseInsensitiveDict):
    """
    There is a weird quirk in HTTP.  You can send the same header twice.  For
    this reason, headers are represented by a dict, with lists as the values.
    However, it appears that HTTPlib is completely incapable of sending the
    same header twice.  This puts me in a weird position: I want to be able to
    accurately represent HTTP headers in cassettes, but I don't want the extra
    step of always having to do [0] in the general case, i.e.
    request.headers['key'][0]

    In addition, some servers sometimes send the same header more than once,
    and httplib *can* deal with this situation.

    Furthermore, I wanted to keep the request and response cassette format as
    similar as possible.

    For this reason, in cassettes I keep a dict with lists as keys, but once
    deserialized into VCR, I keep them as plain, naked dicts.
    """

    def __setitem__(self, key, value):
        if isinstance(value, (tuple, list)):
            value = value[0]

        # Preserve the case from the first time this key was set.
        old = self._store.get(key.lower())
        if old:
            key = old[0]

        super().__setitem__(key, value)
