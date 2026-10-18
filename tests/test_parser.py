"""Smoke tests for the proxy parser.

These verify that the parser handles every shape the upstream sources emit:
plain text, ``ip:port:user:pass``, JSON, full URL forms, and free text with
embedded proxies.
"""

from __future__ import annotations

import pytest

from proxy_scraper.parser import Proxy, parse


def test_parses_plain_ip_port() -> None:
    text = "1.2.3.4:8080\n5.6.7.8:3128\n"
    assert parse(text) == {
        Proxy("1.2.3.4", 8080),
        Proxy("5.6.7.8", 3128),
    }


def test_parses_ip_port_user_pass() -> None:
    text = "1.2.3.4:8080:alice:hunter2\n"
    result = parse(text)
    assert Proxy("1.2.3.4", 8080, "alice", "hunter2") in result


def test_parses_url_form_with_auth() -> None:
    text = "socks5://user:pass@10.0.0.1:1080"
    result = parse(text)
    assert Proxy("10.0.0.1", 1080, "user", "pass") in result


def test_parses_json_data_array() -> None:
    text = '{"data": [{"ip": "1.2.3.4", "port": 80}, {"ip": "5.6.7.8", "port": 3128}]}'
    result = parse(text)
    assert Proxy("1.2.3.4", 80) in result
    assert Proxy("5.6.7.8", 3128) in result


def test_parses_json_list() -> None:
    text = '[{"ip": "1.2.3.4", "port": 80}]'
    result = parse(text)
    assert Proxy("1.2.3.4", 80) in result


def test_dedupes_within_payload() -> None:
    text = "1.2.3.4:80\n1.2.3.4:80\nhttp://1.2.3.4:80"
    result = parse(text)
    assert result == {Proxy("1.2.3.4", 80)}


def test_drops_invalid_ports() -> None:
    text = "1.2.3.4:99999\n1.2.3.4:0\n1.2.3.4:80"
    result = parse(text)
    assert result == {Proxy("1.2.3.4", 80)}


def test_drops_invalid_ips() -> None:
    text = "999.999.999.999:80\n1.2.3.4:80"
    result = parse(text)
    assert result == {Proxy("1.2.3.4", 80)}


def test_parses_from_html_garbage() -> None:
    # Common pattern on free-proxy-list-style sites: ip:port on a line
    # of its own, surrounded by HTML markup.
    text = """
        <html><body>
        <tr><td>1.2.3.4:8080</td></tr>
        <tr><td>5.6.7.8:3128</td></tr>
        </body></html>
    """
    result = parse(text)
    assert Proxy("1.2.3.4", 8080) in result
    assert Proxy("5.6.7.8", 3128) in result


def test_parses_ip_and_port_with_space() -> None:
    # Some sites render IP and port with a space or tab between them.
    text = "1.2.3.4\t8080\n5.6.7.8 3128"
    result = parse(text)
    assert Proxy("1.2.3.4", 8080) in result
    assert Proxy("5.6.7.8", 3128) in result


def test_empty_input() -> None:
    assert parse("") == set()
    assert parse("   \n\n  ") == set()


def test_proxy_to_url_simple() -> None:
    from proxy_scraper.protocols import Protocol

    p = Proxy("1.2.3.4", 80)
    assert p.to_url(Protocol.SOCKS5) == "socks5h://1.2.3.4:80"


def test_proxy_to_url_with_auth() -> None:
    from proxy_scraper.protocols import Protocol

    p = Proxy("1.2.3.4", 80, "user", "pass")
    assert p.to_url(Protocol.HTTP) == "http://user:pass@1.2.3.4:80"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http", "http"),
        ("HTTP", "http"),
        ("https", "http"),
        ("socks4", "socks4"),
        ("SOCKS5", "socks5"),
        ("socks5h", "socks5"),
    ],
)
def test_protocol_parse(raw: str, expected: str) -> None:
    from proxy_scraper.protocols import Protocol

    assert Protocol.parse(raw).value == expected


def test_protocol_parse_invalid() -> None:
    from proxy_scraper.protocols import Protocol

    with pytest.raises(ValueError):
        Protocol.parse("telnet")
