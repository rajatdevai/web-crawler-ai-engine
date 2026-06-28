import pytest
from app.crawler.robots import RobotsTxtParser

def test_robots_txt_wildcard_agent():
    parser = RobotsTxtParser("https://example.com")
    robots_content = "User-agent: *\nDisallow: /admin/\nAllow: /private/public\nDisallow: /private\n"
    parser._parse_content(robots_content)
    
    assert parser.is_allowed("https://example.com/admin/index.html") is False
    assert parser.is_allowed("https://example.com/private/secret.html") is False
    assert parser.is_allowed("https://example.com/private/public/index.html") is True
    assert parser.is_allowed("https://example.com/blog/article") is True

def test_robots_txt_specific_agent():
    parser = RobotsTxtParser("https://example.com")
    robots_content = """
User-agent: AI Categorizer Crawler Bot 1.0
Disallow: /blocked-only-for-bot/
Allow: /

User-agent: *
Disallow: /
"""
    parser._parse_content(robots_content)
    
    # Custom user agent should match specific block and be allowed elsewhere
    assert parser.is_allowed("https://example.com/blocked-only-for-bot/index.html") is False
    assert parser.is_allowed("https://example.com/some-page") is True

def test_robots_txt_sitemaps():
    parser = RobotsTxtParser("https://example.com")
    robots_content = """
User-agent: *
Disallow:

Sitemap: https://example.com/sitemap_index.xml
Sitemap: https://example.com/sitemap_products.xml
"""
    parser._parse_content(robots_content)
    sitemaps = parser.get_sitemaps()
    
    assert "https://example.com/sitemap_index.xml" in sitemaps
    assert "https://example.com/sitemap_products.xml" in sitemaps

def test_robots_txt_missing_file_or_empty():
    parser = RobotsTxtParser("https://example.com")
    # Empty string simulates 404 or 403 where we assume full permission
    parser._parse_content("")
    
    assert parser.is_allowed("https://example.com/any-page") is True
    assert parser.is_allowed("https://example.com/admin/") is True
