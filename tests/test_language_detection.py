from app.rag.preprocessing.language import detect_language


def test_detect_language_unknown_for_empty():
    res = detect_language("", min_chars=1)
    assert res.language == "unknown"
    assert res.confidence == 0.0


def test_detect_language_zh_for_cjk_text():
    res = detect_language("这是一个测试。这是第二句。", min_chars=1)
    assert res.language == "zh"
    assert res.cjk_chars > 0
    assert res.confidence >= 0.6


def test_detect_language_en_for_english_text():
    res = detect_language("This is a test. Another sentence here.", min_chars=1)
    assert res.language == "en"
    assert res.latin_chars > 0
    assert res.confidence >= 0.6


def test_detect_language_mixed_for_mixed_text():
    res = detect_language("Hello 世界 hello 世界", min_chars=1)
    assert res.language == "mixed"
    assert res.cjk_chars > 0
    assert res.latin_chars > 0

