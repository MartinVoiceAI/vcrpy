"""Utilities for patching in cassettes"""

import functools
import http.client as httplib
import logging
from unittest import mock

from .stubs import VCRHTTPConnection, VCRHTTPSConnection

from contextvars import ContextVar
current_cassette = ContextVar("current_cassette")

log = logging.getLogger(__name__)
# Save some of the original types for the purposes of unpatching
_HTTPConnection = httplib.HTTPConnection
_HTTPSConnection = httplib.HTTPSConnection

# Try to save the original types for boto3
try:
    from botocore.awsrequest import AWSHTTPConnection, AWSHTTPSConnection
except ImportError as e:
    try:
        import botocore.vendored.requests  # noqa: F401
    except ImportError:  # pragma: no cover
        pass
    else:
        raise RuntimeError(
            "vcrpy >=4.2.2 and botocore <1.11.0 are not compatible"
            "; please upgrade botocore (or downgrade vcrpy)",
        ) from e
else:
    _Boto3VerifiedHTTPSConnection = AWSHTTPSConnection
    _cpoolBoto3HTTPConnection = AWSHTTPConnection
    _cpoolBoto3HTTPSConnection = AWSHTTPSConnection

cpool = None
conn = None
# Try to save the original types for urllib3
try:
    import urllib3.connection as conn
    import urllib3.connectionpool as cpool
except ImportError:  # pragma: no cover
    pass
else:
    _VerifiedHTTPSConnection = conn.VerifiedHTTPSConnection
    _connHTTPConnection = conn.HTTPConnection
    _connHTTPSConnection = conn.HTTPSConnection

# Try to save the original types for requests
try:
    import requests
except ImportError:  # pragma: no cover
    pass
else:
    if requests.__build__ < 0x021602:
        raise RuntimeError(
            "vcrpy >=4.2.2 and requests <2.16.2 are not compatible"
            "; please upgrade requests (or downgrade vcrpy)",
        )


# Try to save the original types for httplib2
try:
    import httplib2
except ImportError:  # pragma: no cover
    pass
else:
    _HTTPConnectionWithTimeout = httplib2.HTTPConnectionWithTimeout
    _HTTPSConnectionWithTimeout = httplib2.HTTPSConnectionWithTimeout
    _SCHEME_TO_CONNECTION = httplib2.SCHEME_TO_CONNECTION

# Try to save the original types for Tornado
try:
    import tornado.simple_httpclient
except ImportError:  # pragma: no cover
    pass
else:
    _SimpleAsyncHTTPClient_fetch_impl = tornado.simple_httpclient.SimpleAsyncHTTPClient.fetch_impl

try:
    import tornado.curl_httpclient
except ImportError:  # pragma: no cover
    pass
else:
    _CurlAsyncHTTPClient_fetch_impl = tornado.curl_httpclient.CurlAsyncHTTPClient.fetch_impl

try:
    import aiohttp.client
except ImportError:  # pragma: no cover
    pass
else:
    _AiohttpClientSessionRequest = aiohttp.client.ClientSession._request


try:
    import httpx
except ImportError:  # pragma: no cover
    pass
else:
    _HttpxSyncClient_send_single_request = httpx.Client._send_single_request
    _HttpxAsyncClient_send_single_request = httpx.AsyncClient._send_single_request


class CassettePatcherBuilder:


    @staticmethod
    def _build_patchers_from_mock_triples_decorator(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            return CassettePatcherBuilder._build_patchers_from_mock_triples(function(*args, **kwargs))

        return wrapped

    @staticmethod
    def build():
        # Import stubs here to load modules before patching
        try:
            import vcr.stubs.urllib3_stubs
        except ImportError:
            pass
        try:   
            import vcr.stubs.requests_stubs
        except ImportError:
            pass
        try:
                import vcr.stubs.boto3_stubs
        except ImportError:
            pass
        try:
            import vcr.stubs.httplib2_stubs
        except ImportError:
            pass
        try:
            import vcr.stubs.aiohttp_stubs
        except ImportError:
            pass
        try:
            import vcr.stubs.httpx_stubs
        except ImportError:
            pass
        try:
            import vcr.stubs.tornado_stubs
        except ImportError:
            pass

        CassettePatcherBuilder._httplib()
        CassettePatcherBuilder._requests()
        CassettePatcherBuilder._boto3() 
        CassettePatcherBuilder._urllib3()
        CassettePatcherBuilder._httplib2()
        CassettePatcherBuilder._tornado()
        CassettePatcherBuilder._aiohttp()
        CassettePatcherBuilder._httpx()

    @staticmethod
    def _build_patchers_from_mock_triples(mock_triples):
        for args in mock_triples:
            CassettePatcherBuilder._build_patcher(*args)

    @staticmethod
    def _build_patcher(obj, patched_attribute, replacement_class):
        if not hasattr(obj, patched_attribute):
            return
        if hasattr(obj, patched_attribute):
            if isinstance(replacement_class, dict):
                base_obj = getattr(obj, patched_attribute)
                for key, value in replacement_class.items():
                    base_class = base_obj[key]
                    base_obj[key] = value
                    setattr(value, "_baseclass", base_class)
            else:
                base_class = getattr(obj, patched_attribute)
                setattr(obj, patched_attribute, replacement_class)
                setattr(replacement_class, "_baseclass", base_class)

    @staticmethod
    @_build_patchers_from_mock_triples_decorator
    def _httplib():
        yield httplib, "HTTPConnection", VCRHTTPConnection
        yield httplib, "HTTPSConnection", VCRHTTPSConnection

    @staticmethod
    def _requests():
        try:
            from .stubs import requests_stubs
        except ImportError:  # pragma: no cover
            return ()
        CassettePatcherBuilder._urllib3_patchers(cpool, conn, requests_stubs)

    @staticmethod
    @_build_patchers_from_mock_triples_decorator
    def _boto3():
        try:
            # botocore using awsrequest
            import botocore.awsrequest as cpool
        except ImportError:  # pragma: no cover
            pass
        else:
            from .stubs import boto3_stubs

            log.debug("Patching boto3 cpool with %s", cpool)
            yield cpool.AWSHTTPConnectionPool, "ConnectionCls", boto3_stubs.VCRRequestsHTTPConnection
            yield cpool.AWSHTTPSConnectionPool, "ConnectionCls", boto3_stubs.VCRRequestsHTTPSConnection

    @staticmethod
    def _urllib3():
        try:
            import urllib3.connection as conn
            import urllib3.connectionpool as cpool
        except ImportError:  # pragma: no cover
            return ()
        from .stubs import urllib3_stubs

        CassettePatcherBuilder._urllib3_patchers(cpool, conn, urllib3_stubs)

    @staticmethod
    @_build_patchers_from_mock_triples_decorator
    def _httplib2():
        try:
            import httplib2 as cpool
        except ImportError:  # pragma: no cover
            pass
        else:
            from .stubs.httplib2_stubs import VCRHTTPConnectionWithTimeout, VCRHTTPSConnectionWithTimeout

            yield cpool, "HTTPConnectionWithTimeout", VCRHTTPConnectionWithTimeout
            yield cpool, "HTTPSConnectionWithTimeout", VCRHTTPSConnectionWithTimeout
            yield (
                cpool,
                "SCHEME_TO_CONNECTION",
                {
                    "http": VCRHTTPConnectionWithTimeout,
                    "https": VCRHTTPSConnectionWithTimeout,
                },
            )

    @staticmethod
    @_build_patchers_from_mock_triples_decorator
    def _tornado():
        try:
            import tornado.simple_httpclient as simple
        except ImportError:  # pragma: no cover
            pass
        else:
            from .stubs.tornado_stubs import vcr_fetch_impl

            new_fetch_impl = vcr_fetch_impl(_SimpleAsyncHTTPClient_fetch_impl)
            yield simple.SimpleAsyncHTTPClient, "fetch_impl", new_fetch_impl
        try:
            import tornado.curl_httpclient as curl
        except ImportError:  # pragma: no cover
            pass
        else:
            from .stubs.tornado_stubs import vcr_fetch_impl

            new_fetch_impl = vcr_fetch_impl(_CurlAsyncHTTPClient_fetch_impl)
            yield curl.CurlAsyncHTTPClient, "fetch_impl", new_fetch_impl

    @staticmethod
    @_build_patchers_from_mock_triples_decorator
    def _aiohttp():
        try:
            import aiohttp.client as client
        except ImportError:  # pragma: no cover
            pass
        else:
            from .stubs.aiohttp_stubs import vcr_request

            new_request = vcr_request(_AiohttpClientSessionRequest)
            yield client.ClientSession, "_request", new_request

    @staticmethod
    @_build_patchers_from_mock_triples_decorator
    def _httpx():
        try:
            import httpx
        except ImportError:  # pragma: no cover
            return
        else:
            from .stubs.httpx_stubs import async_vcr_send, sync_vcr_send

            new_async_client_send = async_vcr_send(_HttpxAsyncClient_send_single_request)
            yield httpx.AsyncClient, "_send_single_request", new_async_client_send

            new_sync_client_send = sync_vcr_send(_HttpxSyncClient_send_single_request)
            yield httpx.Client, "_send_single_request", new_sync_client_send

    @staticmethod
    def _urllib3_patchers(cpool, conn, stubs):
        mock_triples = (
            (conn, "VerifiedHTTPSConnection", stubs.VCRRequestsHTTPSConnection),
            (conn, "HTTPConnection", stubs.VCRRequestsHTTPConnection),
            (conn, "HTTPSConnection", stubs.VCRRequestsHTTPSConnection),
            (cpool, "is_connection_dropped", mock.Mock(return_value=False)),  # Needed on Windows only
            (cpool.HTTPConnectionPool, "ConnectionCls", stubs.VCRRequestsHTTPConnection),
            (cpool.HTTPSConnectionPool, "ConnectionCls", stubs.VCRRequestsHTTPSConnection),
        )

        CassettePatcherBuilder._build_patchers_from_mock_triples(mock_triples)


