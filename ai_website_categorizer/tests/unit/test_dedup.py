import hashlib
import pytest

def test_content_hash_deduplication():
    # Verify that content hashing is deterministic and produces consistent SHA-256 signatures
    text_1 = "This is a clean page body content with some words."
    text_2 = "This is a clean page body content with some words."
    text_3 = "Different page body content completely."
    
    hash_1 = hashlib.sha256(text_1.encode("utf-8")).hexdigest()
    hash_2 = hashlib.sha256(text_2.encode("utf-8")).hexdigest()
    hash_3 = hashlib.sha256(text_3.encode("utf-8")).hexdigest()
    
    assert hash_1 == hash_2
    assert hash_1 != hash_3
    assert len(hash_1) == 64  # SHA-256 hex length
