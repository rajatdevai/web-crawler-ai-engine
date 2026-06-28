import urllib.parse
import hashlib
from typing import Optional
import tldextract

def extract_domain(url: str) -> str:
    """Extracts registrable domain (e.g. blog.amazon.co.uk -> amazon.co.uk)."""
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain

def is_internal_url(url: str, base_url: str) -> bool:
    """Checks if a URL belongs to the same registrable domain family as the seed URL."""
    try:
        url_domain = extract_domain(url)
        base_domain = extract_domain(base_url)
        return url_domain == base_domain and bool(url_domain)
    except Exception:
        return False

def is_crawlable_url(url: str) -> bool:
    """Rejects non-HTTP schemas."""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme in ("http", "https")
    except Exception:
        return False

def normalize_url(url: str, base_url: Optional[str] = None) -> str:
    """
    Resolves relative URLs against base.
    Lowercases scheme and host.
    Removes default ports and fragments.
    Removes tracking parameters and sorts query parameters.
    """
    if base_url:
        url = urllib.parse.urljoin(base_url, url)
        
    parsed = urllib.parse.urlparse(url)
    
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    
    # Remove default ports
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Filter query parameters
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    tracking_params = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
    
    filtered_query = [(k, v) for k, v in query_params if k.lower() not in tracking_params]
    filtered_query.sort() # Sort to ensure consistent order
    
    new_query = urllib.parse.urlencode(filtered_query)
    
    # Reconstruct url without fragment
    normalized_parsed = urllib.parse.ParseResult(
        scheme=scheme,
        netloc=netloc,
        path=parsed.path or "/",
        params=parsed.params,
        query=new_query,
        fragment=""
    )
    
    return urllib.parse.urlunparse(normalized_parsed)

def compute_url_fingerprint(url: str) -> str:
    """Returns SHA256 of the normalized URL for deduplication."""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()
