"""Unit tests for P0 chunk quality optimizations.

Tests:
- Minimum chunk size validation
- Context Cliff detection
- Integration with existing quality scoring
"""

import pytest

from app.rag.chunking.quality_scorer import (
    CONTEXT_CLIFF_DANGER,
    CONTEXT_CLIFF_WARNING,
    MAX_CHUNK_SIZE_TOKENS,
    MIN_CHUNK_SIZE_TOKENS,
    OPTIMAL_CHUNK_RANGE,
    detect_context_cliff,
    score_chunk_semantic_quality,
    validate_chunk_size_bounds,
)


class TestChunkSizeBounds:
    """Test minimum and maximum chunk size validation."""

    def test_chunk_too_small(self):
        """Test detection of chunks below minimum size."""
        result = validate_chunk_size_bounds(50)

        assert result["is_valid"] is False
        assert result["size_category"] == "too_small"
        assert result["severity"] == "critical"
        assert result["recommendation"] == f"merge_to_{MIN_CHUNK_SIZE_TOKENS}"
        assert str(MIN_CHUNK_SIZE_TOKENS) in result["warning"]

    def test_chunk_too_large(self):
        """Test detection of chunks above maximum size."""
        result = validate_chunk_size_bounds(1500)

        assert result["is_valid"] is False
        assert result["size_category"] == "too_large"
        assert result["severity"] == "critical"
        assert result["recommendation"] == f"split_to_{OPTIMAL_CHUNK_RANGE[1]}"

    def test_chunk_below_optimal(self):
        """Test chunks below optimal range but above minimum."""
        result = validate_chunk_size_bounds(150)

        assert result["is_valid"] is True
        assert result["size_category"] == "below_optimal"
        assert result["severity"] == "warning"
        assert result["recommendation"] == "consider_merge"

    def test_chunk_above_optimal(self):
        """Test chunks above optimal range but below maximum."""
        result = validate_chunk_size_bounds(700)

        assert result["is_valid"] is True
        assert result["size_category"] == "above_optimal"
        assert result["severity"] == "info"
        assert result["recommendation"] == "consider_split"

    def test_chunk_optimal(self):
        """Test chunks in optimal range."""
        for tokens in [200, 300, 400, 512]:
            result = validate_chunk_size_bounds(tokens)

            assert result["is_valid"] is True
            assert result["size_category"] == "optimal"
            assert result["severity"] == "none"
            assert result["warning"] is None

    def test_edge_cases(self):
        """Test boundary values."""
        # Exactly at minimum
        result = validate_chunk_size_bounds(MIN_CHUNK_SIZE_TOKENS)
        assert result["is_valid"] is True

        # Just below minimum
        result = validate_chunk_size_bounds(MIN_CHUNK_SIZE_TOKENS - 1)
        assert result["is_valid"] is False

        # Exactly at maximum
        result = validate_chunk_size_bounds(MAX_CHUNK_SIZE_TOKENS)
        assert result["is_valid"] is True

        # Just above maximum
        result = validate_chunk_size_bounds(MAX_CHUNK_SIZE_TOKENS + 1)
        assert result["is_valid"] is False


class TestContextCliffDetection:
    """Test Context Cliff detection based on Anthropic research."""

    def test_no_cliff_risk(self):
        """Test chunks in safe range with no cliff risk."""
        result = detect_context_cliff(300)

        assert result["cliff_risk"] == "none"
        assert result["severity"] == "none"
        assert result["action"] == "none"
        assert result["estimated_recall"] == 0.92

    def test_low_cliff_risk(self):
        """Test chunks above optimal but below warning threshold."""
        result = detect_context_cliff(800)

        assert result["cliff_risk"] == "low"
        assert result["severity"] == "info"
        assert result["action"] == "monitor"
        assert result["estimated_recall"] == 0.88

    def test_medium_cliff_risk(self):
        """Test chunks in warning zone."""
        result = detect_context_cliff(2200)

        assert result["cliff_risk"] == "medium"
        assert result["severity"] == "warning"
        assert result["action"] == "consider_split"
        assert result["estimated_recall"] == 0.75
        assert result["target_sizes"] == [1000, 1200]

    def test_high_cliff_risk(self):
        """Test chunks in danger zone."""
        result = detect_context_cliff(3000)

        assert result["cliff_risk"] == "high"
        assert result["severity"] == "critical"
        assert result["action"] == "split_required"
        assert result["estimated_recall"] == 0.55
        assert result["target_sizes"] == [600, 800, 1000]

    def test_cliff_thresholds(self):
        """Test behavior at exact threshold values."""
        # Just below warning
        result = detect_context_cliff(CONTEXT_CLIFF_WARNING - 1)
        assert result["cliff_risk"] in ("none", "low")

        # At warning threshold
        result = detect_context_cliff(CONTEXT_CLIFF_WARNING)
        assert result["cliff_risk"] == "medium"

        # Just below danger
        result = detect_context_cliff(CONTEXT_CLIFF_DANGER - 1)
        assert result["cliff_risk"] == "medium"

        # At danger threshold
        result = detect_context_cliff(CONTEXT_CLIFF_DANGER)
        assert result["cliff_risk"] == "high"


class TestIntegrationWithQualityScoring:
    """Test integration of P0 optimizations with existing quality scoring."""

    def test_small_chunk_flagged(self):
        """Test that small chunks are flagged in quality scoring."""
        # Generate a small chunk (< 100 tokens, roughly < 400 chars)
        small_text = "This is a very short chunk. Too small for good retrieval."

        scores, _ = score_chunk_semantic_quality(small_text, tokens_est=30)

        assert scores["needs_review"] is True
        assert "too_small" in scores["reasons"]
        assert scores["size_validation"]["is_valid"] is False
        assert scores["size_validation"]["severity"] == "critical"

    def test_large_chunk_flagged(self):
        """Test that large chunks are flagged in quality scoring."""
        # Simulate a large chunk
        large_text = "word " * 5000  # Roughly 1200+ tokens

        scores, _ = score_chunk_semantic_quality(large_text, tokens_est=1200)

        assert scores["needs_review"] is True
        assert "too_large" in scores["reasons"]
        assert scores["size_validation"]["is_valid"] is False

    def test_cliff_risk_flagged(self):
        """Test that Context Cliff risk is flagged."""
        # Simulate a chunk at cliff threshold
        cliff_text = "word " * 12000  # Roughly 2500+ tokens

        scores, _ = score_chunk_semantic_quality(cliff_text, tokens_est=2600)

        assert scores["needs_review"] is True
        assert "cliff_risk_high" in scores["reasons"]
        assert scores["context_cliff"]["cliff_risk"] == "high"
        assert scores["context_cliff"]["severity"] == "critical"

    def test_optimal_chunk_not_flagged(self):
        """Test that optimal chunks pass validation."""
        optimal_text = "This is a well-sized chunk. " * 40  # Roughly 300 tokens

        scores, _ = score_chunk_semantic_quality(optimal_text, tokens_est=300)

        # Should not be flagged for size issues
        assert "too_small" not in scores["reasons"]
        assert "too_large" not in scores["reasons"]
        assert "cliff_risk_high" not in scores["reasons"]
        assert "cliff_risk_medium" not in scores["reasons"]

        assert scores["size_validation"]["is_valid"] is True
        assert scores["size_validation"]["size_category"] == "optimal"
        assert scores["context_cliff"]["cliff_risk"] == "none"

    def test_metadata_included(self):
        """Test that P0 metadata is included in scores."""
        text = "Test chunk content."

        scores, _ = score_chunk_semantic_quality(text, tokens_est=250)

        # Check that new P0 fields are present
        assert "size_validation" in scores
        assert "context_cliff" in scores
        assert "token_count" in scores

        # Check structure
        assert "is_valid" in scores["size_validation"]
        assert "cliff_risk" in scores["context_cliff"]
        assert isinstance(scores["token_count"], int)


class TestRealWorldScenarios:
    """Test with real-world chunk scenarios."""

    def test_pdf_paragraph_chunk(self):
        """Test typical PDF paragraph chunk (200-400 tokens)."""
        text = (
            """
        根据《中华人民共和国公司法》的相关规定，公司章程是规范公司组织和行为、
        确定公司及其股东、董事、监事、高级管理人员权利义务关系的具有法律约束力
        的文件。本章程经公司股东大会表决通过后生效，对公司、股东、董事、监事、
        高级管理人员具有法律约束力。公司应当将章程置备于公司住所，供股东查阅。
        """
            * 3
        )  # Repeat to get ~300 tokens

        scores, _ = score_chunk_semantic_quality(text, tokens_est=320)

        assert scores["size_validation"]["size_category"] == "optimal"
        assert scores["context_cliff"]["cliff_risk"] == "none"
        assert scores["size_validation"]["is_valid"] is True

    def test_code_function_chunk(self):
        """Test typical code function chunk."""
        text = '''
        def process_document(doc_path: str, config: dict) -> dict:
            """
            Process a document through the RAG pipeline.
            
            Args:
                doc_path: Path to the document file
                config: Processing configuration
                
            Returns:
                Processing results with metadata
            """
            try:
                # Load document
                content = load_file(doc_path)
                
                # Parse content
                parsed = parse_document(content, config.get("parser"))
                
                # Chunk content
                chunks = chunk_document(parsed, config.get("chunking"))
                
                # Generate embeddings
                embeddings = embed_chunks(chunks, config.get("embedding"))
                
                # Store in vector DB
                store_embeddings(embeddings, config.get("vector_db"))
                
                return {
                    "status": "success",
                    "chunks": len(chunks),
                    "doc_path": doc_path
                }
            except Exception as e:
                logger.error(f"Processing failed: {e}")
                return {"status": "failed", "error": str(e)}
        '''

        scores, _ = score_chunk_semantic_quality(text, tokens_est=280)

        assert scores["size_validation"]["is_valid"] is True
        assert scores["context_cliff"]["cliff_risk"] == "none"

    def test_table_chunk(self):
        """Test table/structured data chunk (often smaller)."""
        text = """
        | 产品名称 | 规格 | 单价 | 数量 |
        |---------|------|------|------|
        | 产品A   | 标准 | 100  | 50   |
        | 产品B   | 高级 | 200  | 30   |
        | 产品C   | 豪华 | 500  | 10   |
        """

        scores, _ = score_chunk_semantic_quality(text, tokens_est=80)

        assert scores["size_validation"]["size_category"] == "too_small"
        assert scores["size_validation"]["severity"] == "critical"

    def test_long_legal_document_chunk(self):
        """Test overly long legal document chunk."""
        text = "第一条 " + "根据相关法律法规，" * 1500  # Simulate ~3000 tokens

        scores, _ = score_chunk_semantic_quality(text, tokens_est=3000)

        assert scores["needs_review"] is True
        assert scores["context_cliff"]["cliff_risk"] == "high"
        assert scores["context_cliff"]["action"] == "split_required"
        assert 600 in scores["context_cliff"]["target_sizes"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
