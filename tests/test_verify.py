"""Mechanical quote checker: normalization, value formats, rewrites, SSRF."""

import pytest

from agentdao.verify import (FetchError, FetchResult, QuoteChecker, SafeFetcher, ip_is_public, normalize,
                             rewrite_url, validate_url, value_in_text)
from conftest import QUOTE, SOURCE, FakeFetcher


def test_quote_check_passes_with_html_and_entities():
    f = FakeFetcher()
    qc = QuoteChecker(f)
    r = qc.check(SOURCE, "resolves 72.4% of tasks with Claude & tools", 72.4)
    assert r["passed"] and r["reason"] == "ok" and r["content_sha256"]
    assert qc.check(SOURCE, QUOTE, 0.724)["passed"]  # fraction form of the same value
    qc.check(SOURCE, QUOTE, 72.4)
    assert f.calls == [SOURCE]  # cached


def test_quote_check_failures():
    qc = QuoteChecker(FakeFetcher())
    assert qc.check(SOURCE, "short", 1)["reason"] == "quote_length"
    assert qc.check(SOURCE, QUOTE, 99.9)["reason"] == "value_not_in_quote"
    assert qc.check("https://missing.example/x", QUOTE, 72.4)["reason"] == "http_error"


def test_pdf_is_unverifiable():
    f = FakeFetcher()
    f.pages["https://example.org/p.pdf"] = FetchResult("https://example.org/p.pdf", 200, "application/pdf", b"%PDF")
    assert QuoteChecker(f).check("https://example.org/p.pdf", QUOTE, 72.4)["reason"] == "unverifiable_format"


def test_normalization_and_values():
    assert normalize("“Smart” quotes — and spaces") == '"smart" quotes - and spaces'
    assert value_in_text(72.4, "scored 72.4% overall") and value_in_text(72.4, "a score of 0.724")
    assert not value_in_text(72.4, "scored 72.45 overall") and not value_in_text(7.2, "scored 72.4")


def test_rewrites():
    assert rewrite_url("https://github.com/o/r/blob/main/README.md") == ["https://raw.githubusercontent.com/o/r/main/README.md"]
    assert rewrite_url("https://arxiv.org/abs/2401.00001") == ["https://arxiv.org/abs/2401.00001", "https://arxiv.org/html/2401.00001"]


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.3.4", "169.254.169.254",
                                "::1", "fe80::1", "fd00::1", "100.64.0.1", "0.0.0.0", "::ffff:127.0.0.1"])
def test_private_ips_blocked(ip):
    assert not ip_is_public(ip)
    with pytest.raises(FetchError) as e:
        validate_url("https://evil.example/x", lambda h: [ip])
    assert e.value.reason == "blocked_url"


def test_scheme_and_public_ip_rules():
    assert ip_is_public("93.184.216.34")
    with pytest.raises(FetchError):
        validate_url("http://example.org/", lambda h: ["93.184.216.34"])  # http refused
    with pytest.raises(FetchError):
        validate_url("https://user:pw@example.org/", lambda h: ["93.184.216.34"])
    # any one private address in the answer set blocks (DNS rebinding style)
    with pytest.raises(FetchError):
        validate_url("https://example.org/", lambda h: ["93.184.216.34", "10.0.0.1"])


def test_safe_fetcher_refuses_private_host_without_connecting():
    f = SafeFetcher(resolver=lambda h: ["127.0.0.1"])
    r = QuoteChecker(f).check("https://localhost.evil/x", QUOTE, 72.4)
    assert not r["passed"] and r["reason"] == "blocked_url"


def test_stripped_tags_become_spaces():
    """Quotes copied from rendered HTML tables must match: adjacent cells are separated by whitespace, not glued."""
    f = FakeFetcher()
    url = "https://example.org/table"
    f.pages[url] = FetchResult(url, 200, "text/html",
                               b"<table><tr><td>Foo-Agent</td><td>SWE-bench Verified</td><td>72.4</td></tr></table>")
    assert QuoteChecker(f).check(url, "Foo-Agent SWE-bench Verified 72.4", 72.4)["passed"]


def test_http_localhost_only_behind_flag():
    with pytest.raises(FetchError):
        validate_url("http://localhost:8799/x", lambda h: ["127.0.0.1"])
    assert validate_url("http://localhost:8799/x", lambda h: [], allow_http_localhost=True) == ("localhost", [])
    assert validate_url("http://[::1]:8799/x", lambda h: [], allow_http_localhost=True)[0] == "::1"
    with pytest.raises(FetchError):  # flag never opens non-loopback http
        validate_url("http://example.org/x", lambda h: ["93.184.216.34"], allow_http_localhost=True)


def test_markdown_with_embedded_html_table():
    """Model-card READMEs (text/plain) often embed <table> results; quotes copied from the rendered card must match."""
    f = FakeFetcher()
    url = "https://example.org/README.md"
    f.pages[url] = FetchResult(url, 200, "text/plain", (
        b"# Model\n\n<table><tr><td align=\"center\">GPQA Diamond</td>\n<td> 93.5 </td><td>92.6</td></tr></table>\n"
        b"| SWE-bench | **80.2** |\n"))
    qc = QuoteChecker(f)
    assert qc.check(url, "GPQA Diamond 93.5 92.6", 93.5)["passed"]
    assert qc.check(url, "| SWE-bench | **80.2** |", 80.2)["passed"]  # raw markdown still matches
