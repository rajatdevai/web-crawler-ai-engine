import hashlib

def get_url_hash(url: str) -> str:
    """
    Generate SHA256 fingerprint for a normalized URL.
    This is used for deduplication across the pipeline.
    The hash must be computed after URL normalization.
    """
    return hashlib.sha256(url.encode("utf-8")).hexdigest()

def get_content_hash(content: str) -> str:
    """
    Generate SHA256 fingerprint for page body content.
    If a page is recrawled and content hasn't changed, downstream processing is skipped.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
