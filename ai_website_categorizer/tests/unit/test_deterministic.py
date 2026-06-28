import pytest
from app.categorizer.deterministic import DeterministicClassifier

def test_deterministic_classifier_url_signal():
    classifier = DeterministicClassifier()
    classifier.threshold = 0.70
    
    # URL path contains 'gummy' -> matches 'Gummies'
    doc = {
        "title": "CBD Gummies",
        "h1_tags": ["CBD Gummies"],
        "breadcrumbs": [],
        "structured_data": [],
    }
    res = classifier.classify(doc, page_url="https://example.com/cbd-gummies")
    
    assert res.matched_category == "Gummies"
    assert res.confidence >= 0.70
    assert any(s.field == "url_path" and s.keyword == "gummies" for s in res.matched_signals)

def test_deterministic_classifier_title_signal():
    classifier = DeterministicClassifier()
    classifier.threshold = 0.70
    
    # Title contains 'capsules' -> matches 'Capsules'
    doc = {
        "title": "Collagen Capsules",
        "h1_tags": ["Collagen Capsules"],
        "breadcrumbs": [],
        "structured_data": [],
    }
    res = classifier.classify(doc, page_url="https://example.com/capsules-detail")
    
    assert res.matched_category == "Capsules"
    assert res.confidence >= 0.70
    assert any(s.field == "title" and s.keyword == "capsules" for s in res.matched_signals)

def test_deterministic_classifier_below_threshold():
    classifier = DeterministicClassifier()
    
    # Very weak signals (contains 'drops' in H2 but nowhere else)
    # This should return matched_category=None because confidence is below threshold
    doc = {
        "title": "Welcome to our supplement shop",
        "h1_tags": ["Shop healthy today"],
        "h2_tags": ["Herbal drops"],
        "breadcrumbs": [],
        "structured_data": [],
    }
    res = classifier.classify(doc, page_url="https://example.com/home")
    
    assert res.matched_category is None
    # Partial confidence score is still returned
    assert res.confidence < 0.90

def test_deterministic_classifier_skipped_utility():
    classifier = DeterministicClassifier()
    
    # Utility path (/cart) -> returns skipped=True
    doc = {
        "title": "Your Shopping Cart",
        "h1_tags": ["Cart"],
    }
    res = classifier.classify(doc, page_url="https://example.com/cart")
    assert res.skipped is True
    assert res.matched_category is None
