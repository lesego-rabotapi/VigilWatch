import pytest

from common.urlguard import UnresolvableHost, UnsafeURL, endpoint_id, normalize, validate

DNS = {
    "example.com": ["93.184.215.14"],
    "v6.example.com": ["2606:2800:21f:cb07:6820:80da:af6b:8b2c"],
    "localhost": ["127.0.0.1"],
    "internal.corp": ["10.1.2.3"],
    "rebind.evil": ["93.184.215.14", "169.254.169.254"],
    "2130706433": ["127.0.0.1"],  # decimal form of 127.0.0.1
}


def fake_resolver(host):
    if host not in DNS:
        raise UnresolvableHost(host)
    return DNS[host]


def check(url):
    return validate(url, resolver=fake_resolver)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com/health?x=1",
        "https://example.com:8443/status",
        "https://v6.example.com/",
        "https://93.184.215.14/",
    ],
)
def test_public_urls_are_allowed(url):
    assert check(url).startswith(("http://", "https://"))


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
        "javascript:alert(1)",
        "example.com",
        "https://",
        "",
        "   ",
        "https://user:pw@example.com/",
        "https://example.com/" + "a" * 2050,
        "https://example.com:0/",
        "https://example.com:99999/",
    ],
)
def test_malformed_or_disallowed_urls_are_rejected(url):
    with pytest.raises(UnsafeURL):
        check(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.1.2.3:9001/2018-06-01/runtime/invocation/next",  # Lambda runtime API
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fe80::1]/",
        "http://10.0.0.1/",
        "http://172.16.5.4/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",  # carrier-grade NAT
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://localhost/",
        "http://internal.corp/",
        "http://rebind.evil/",  # any private record poisons the whole host
        "http://2130706433/",
    ],
)
def test_private_and_special_addresses_are_rejected(url):
    with pytest.raises(UnsafeURL):
        check(url)


def test_unresolvable_host_is_its_own_error():
    with pytest.raises(UnresolvableHost):
        check("https://does-not-exist.invalid/")


def test_unresolvable_is_also_unsafe_for_callers_that_only_catch_unsafe():
    assert issubclass(UnresolvableHost, UnsafeURL)


def test_normalize_is_canonical():
    assert normalize("  HTTPS://Example.COM:443/Path?q=1#frag ") == "https://example.com/Path?q=1"
    assert normalize("http://example.com:80") == "http://example.com/"
    assert normalize("https://example.com:8443/x") == "https://example.com:8443/x"


def test_endpoint_id_is_stable_and_case_insensitive_on_host():
    a = endpoint_id(normalize("https://EXAMPLE.com/"))
    b = endpoint_id(normalize("https://example.com"))
    assert a == b
    assert len(a) == 16
    assert a != endpoint_id(normalize("https://example.org/"))
