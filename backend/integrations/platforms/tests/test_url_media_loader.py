import pytest
from urllib.error import HTTPError
from urllib.request import Request

from integrations.platforms.runtime import UrlMediaLoader, _NoRedirectHandler


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return b"media-bytes"


def fake_opener(request, timeout=None):
    return FakeResponse()


def resolver_for(*addresses):
    def resolver(hostname, port):
        return [(None, None, None, None, (address, 0)) for address in addresses]

    return resolver


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.1.2.3",),
        ("192.168.0.5",),
        ("169.254.169.254",),
        ("172.16.0.1",),
        ("::1",),
        ("fd00::1",),
    ],
)
def test_media_loader_rejects_non_public_hosts(addresses):
    loader = UrlMediaLoader(opener=fake_opener, resolver=resolver_for(*addresses))

    with pytest.raises(ValueError, match="public address"):
        loader.load("https://internal.example.com/video.mp4", 1024)


def test_media_loader_rejects_unresolvable_host():
    def failing_resolver(hostname, port):
        import socket

        raise socket.gaierror("dns failure")

    loader = UrlMediaLoader(opener=fake_opener, resolver=failing_resolver)

    with pytest.raises(ValueError, match="could not be resolved"):
        loader.load("https://missing.example.com/video.mp4", 1024)


def test_media_loader_allows_public_host():
    loader = UrlMediaLoader(
        opener=fake_opener, resolver=resolver_for("93.184.216.34")
    )

    assert loader.load("https://cdn.example.com/video.mp4", 1024) == b"media-bytes"


def test_media_loader_rejects_missing_host_and_plain_http():
    loader = UrlMediaLoader(
        opener=fake_opener, resolver=resolver_for("93.184.216.34")
    )

    with pytest.raises(ValueError, match="HTTPS"):
        loader.load("http://cdn.example.com/video.mp4", 1024)
    with pytest.raises(ValueError, match="host"):
        loader.load("https:///video.mp4", 1024)


def test_no_redirect_handler_blocks_redirects():
    handler = _NoRedirectHandler()
    request = Request("https://cdn.example.com/video.mp4")

    with pytest.raises(HTTPError):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {"Location": "http://169.254.169.254/latest/meta-data/"},
            "http://169.254.169.254/latest/meta-data/",
        )


def test_media_loader_pins_the_first_public_address():
    loader = UrlMediaLoader(
        opener=fake_opener,
        resolver=resolver_for("93.184.216.34", "93.184.216.35"),
    )

    assert loader._resolve_public_ip("cdn.example.com") == "93.184.216.34"
