import pytest
from app.crawler.url_utils import normalize_url, extract_domain, is_internal_url, is_crawlable_url

def test_extract_domain():
    assert extract_domain("https://blog.amazon.co.uk/path") == "amazon.co.uk"
    assert extract_domain("http://amazon.com/") == "amazon.com"
    assert extract_domain("https://sub.domain.test.org") == "test.org"

def test_is_internal_url():
    assert is_internal_url("https://blog.amazon.co.uk/path", "https://amazon.co.uk") is True
    assert is_internal_url("https://google.com", "https://amazon.co.uk") is False

def test_is_crawlable_url():
    assert is_crawlable_url("https://amazon.com") is True
    assert is_crawlable_url("http://amazon.com") is True
    assert is_crawlable_url("ftp://amazon.com") is False
    assert is_crawlable_url("file:///etc/passwd") is False

def test_normalize_url_basic():
    assert normalize_url("HTTPS://AMAZON.COM:443/Path/") == "https://amazon.com/Path/"
    assert normalize_url("http://AMAZON.COM:80/") == "http://amazon.com/"

def test_normalize_url_relative():
    assert normalize_url("/relative/path", "https://amazon.com/base") == "https://amazon.com/relative/path"
    assert normalize_url("subpath", "https://amazon.com/base/") == "https://amazon.com/base/subpath"

def test_normalize_url_params_and_fragments():
    # Removes fragments
    assert normalize_url("https://amazon.com/path#fragment") == "https://amazon.com/path"
    
    # Removes UTM and tracking query parameters, sorts the rest
    url_with_tracking = "https://amazon.com/path?utm_source=google&b=2&a=1&fbclid=123"
    assert normalize_url(url_with_tracking) == "https://amazon.com/path?a=1&b=2"
