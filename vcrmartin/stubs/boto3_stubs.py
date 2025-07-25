"""Stubs for boto3"""

from botocore.awsrequest import AWSHTTPConnection as HTTPConnection
from botocore.awsrequest import AWSHTTPSConnection as VerifiedHTTPSConnection

from ..stubs import VCRHTTPConnection, VCRHTTPSConnection


class VCRRequestsHTTPConnection(VCRHTTPConnection, HTTPConnection):
    _baseclass = HTTPConnection


class VCRRequestsHTTPSConnection(VCRHTTPSConnection, VerifiedHTTPSConnection):
    _baseclass = VerifiedHTTPSConnection

    def __init__(self, *args, **kwargs):
        kwargs.pop("strict", None)

        self.real_connection = self._baseclass(*args, **kwargs)
        # Make sure to set those attributes as it seems `AWSHTTPConnection` does not
        # set them, making the connection to fail !
        self.real_connection.assert_hostname = kwargs.get("assert_hostname", False)
        self.real_connection.cert_reqs = kwargs.get("cert_reqs", "CERT_NONE")

        self._sock = None
