"""Deterministic result_digest generation. Digests are what the executor and
synthesizer LLMs actually see (never raw_result), so they must be short,
factual, and stay within an 80-token budget. We approximate tokens as
whitespace-split words (a documented, conservative proxy — see README
limitations); it under-counts subword tokenization slightly, so we budget
to 60 words to leave headroom.
"""

MAX_DIGEST_WORDS = 60


def estimate_tokens(s: str) -> int:
    return len(s.split())


def truncate_to_budget(s: str, max_words: int = MAX_DIGEST_WORDS) -> str:
    words = s.split()
    if len(words) <= max_words:
        return s
    return " ".join(words[:max_words]) + " …[truncated]"
