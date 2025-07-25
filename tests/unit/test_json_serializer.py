import pytest

from vcrmartin.request import Request
from vcrmartin.serializers.jsonserializer import serialize


def test_serialize_binary():
    request = Request(method="GET", uri="http://localhost/", body="", headers={})
    cassette = {"requests": [request], "responses": [{"body": b"\x8c"}]}

    with pytest.raises(Exception) as e:
        serialize(cassette)
        assert (
            e.message
            == "Error serializing cassette to JSON. Does this \
            HTTP interaction contain binary data? If so, use a different \
            serializer (like the yaml serializer) for this request"
        )
