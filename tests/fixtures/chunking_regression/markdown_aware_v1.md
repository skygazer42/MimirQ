# Chunking Fixture: Markdown Aware

This markdown document is a regression fixture for chunking strategies that pay attention to
headings, lists, and code fences.

## Install

1. Download the package.
2. Verify the checksum.
3. Run the installer with default settings.

## Usage

- Use short examples.
- Keep the content deterministic.
- Avoid external references.

```python
def add(a: int, b: int) -> int:
    return a + b
```

## Notes

The splitter should not break inside the code fence, and headings should remain near their
associated content where possible.

