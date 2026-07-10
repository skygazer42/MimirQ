
import hashlib


def embed_code_snippet(code: str, *, dimension: int = 256) -> list[float]:
    dim = max(1, int(dimension or 1))
    digest = hashlib.sha256(str(code or "").encode("utf-8", "ignore")).digest()
    out: list[float] = []
    while len(out) < dim:
        for byte in digest:
            out.append(round(float(byte) / 255.0, 6))
            if len(out) >= dim:
                break
        digest = hashlib.sha256(digest).digest()
    return out


__all__ = ["embed_code_snippet"]
