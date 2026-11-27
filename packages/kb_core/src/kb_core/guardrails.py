"""Guardrails around the answer (Phase 7b): checks in code, before and after the model.

Three checks, all deterministic, free and fast, so they run on every request:

1. **Input screen.** Blocks questions that try to change the assistant's rules ("ignore
   your instructions", "developer mode", "print your system prompt", fake <source> tags)
   before retrieval or the model run. $0, no tokens, and no second chance for a model to
   be talked round. The system-prompt rule (incident 0010) stays as the second layer.
2. **Refusal detection.** "Not found" in its many phrasings, not only the exact sentence
   (incident 0009: a hedged non-answer passed as an answer). An answer that cites a
   retrieved source is never a refusal, even if it says part of the question isn't covered.
3. **Grounding check.** Every sentence of the answer should cite a source and share most
   of its content words with the sources it cites. Terms that appear in no retrieved
   chunk (an Azure "LRS" in an answer about S3, seen in Phase 6b) are listed.

These are cheap heuristics, not proofs. They catch the common failures and give metrics
and evaluation a signal; an LLM judge (`kb eval --judge`) or Bedrock Guardrails' contextual
grounding check is the stronger, slower and paid option (ADR 0017).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from kb_core.models import Grounding, RetrievedChunk

# --- 1. input screen --------------------------------------------------------------

# Each pattern names an *instruction to the assistant*, not a topic. Architecture questions
# use words like "system", "ignore" and "instructions" all the time ("should the system
# ignore failed health checks?"), so single words are never enough to block.
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(rx, re.IGNORECASE))
    for name, rx in (
        (
            "override_instructions",
            r"\b(ignore|disregard|forget|override|bypass)\b(\s+\w+){0,4}?\s+"
            r"(instructions?|rules|guidelines|prompts?|directions|constraints)\b",
        ),
        ("mode_switch", r"\b(developer|dev|debug|god|admin|jailbreak|dan|unrestricted)\s+mode\b"),
        ("role_change", r"\byou\s+are\s+now\b|\bpretend\s+(to\s+be|you\s+are)\b|\bact\s+as\s+if\b"),
        (
            "prompt_extraction",
            r"\b(reveal|show|print|repeat|output|display|tell\s+me|what\s+(is|are))\b(\s+\w+){0,4}?\s+"
            r"(system\s+prompt|hidden\s+instructions|your\s+(instructions|rules|prompt))\b",
        ),
        (
            "no_sources",
            r"\b(answer|reply|respond)\b(\s+\w+){0,3}?\s+without\s+(the\s+|any\s+)?(sources|citations|context)\b",
        ),
        ("fake_markup", r"</?\s*(source|system|assistant|instructions?)\b[^>]*>|^\s*system\s*:"),
    )
)


@dataclass(frozen=True)
class Screen:
    blocked: bool
    reason: str | None = None  # pattern name, for metrics and traces; never shown to users


def screen_question(question: str) -> Screen:
    text = unicodedata.normalize("NFKC", question)
    for name, pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return Screen(blocked=True, reason=name)
    return Screen(blocked=False)


# --- 2. refusal detection ---------------------------------------------------------

_REFUSAL = re.compile(
    r"(couldn'?t|could not|can'?t|cannot|unable to|did not|didn'?t)\s+find"
    # "not (explicitly) stated in the provided sources" (incident 0009's hedged refusal)
    r"|not\s+(\w+ly\s+)?(found|covered|mentioned|addressed|included|described|stated|listed"
    r"|specified|provided)\s+in\s+(the\s+)?(provided\s+|given\s+)?"
    r"(knowledge\s*base|sources|documents|context)"
    r"|(the\s+)?(provided\s+|given\s+)?(sources|documents|context|knowledge\s*base)\s+"
    r"(do(es)?\s*n[o']t|does not|do not)\s+(\w+ly\s+)?"
    r"(contain|mention|cover|include|provide|say|address|list|state|specify|describe)"
    r"|no\s+(relevant\s+)?information\s+(about|on|regarding|in)",
    re.IGNORECASE,
)
_CITATION = re.compile(r"\[(\d+)\]")


def valid_citations(text: str, source_count: int) -> set[int]:
    return {int(n) for n in _CITATION.findall(text) if 1 <= int(n) <= source_count}


def is_refusal(text: str, source_count: int) -> bool:
    """A refusal says "not found" in some phrasing AND cites nothing it was given.

    Citing a source means the model used it, so the answer counts as an answer even when
    it also says part of the question isn't covered.
    """
    if not text.strip():
        return True
    return bool(_REFUSAL.search(_plain(text))) and not valid_citations(text, source_count)


# --- 3. grounding check -----------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z0-9][a-z0-9\-]*")
# A capitalised term or acronym that could be a product, service or standard name.
_TERM = re.compile(r"\b([A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*|[A-Z]{2,}[0-9]*)\b")
_STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "also",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "here",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "may",
        "more",
        "most",
        "must",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "out",
        "over",
        "own",
        "same",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "use",
        "used",
        "using",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "can't",
        "cannot",
        "don't",
        "doesn't",
        "should",
        "also",
        "e.g",
        "i.e",
        "etc",
        "via",
        "per",
    ]
)
# Words a sentence adds to structure an answer, not claims ("Here are the key points:").
_FILLER = frozenset(
    [
        "here",
        "key",
        "points",
        "following",
        "summary",
        "sources",
        "source",
        "according",
        "recommends",
    ]
)

SUPPORT_THRESHOLD = 0.5  # share of a sentence's content words found in its cited chunks


def check_grounding(text: str, chunks: Sequence[RetrievedChunk]) -> Grounding:
    """Score how well each sentence is backed by the sources it cites.

    A claim is a sentence with at least 3 content words. It's supported when it cites a
    retrieved chunk and at least half of its content words appear in the chunks it cites.
    Uncited claims are unsupported. Short connective sentences aren't claims.
    """
    chunk_words = [_words(c.chunk.text + " " + c.chunk.section) for c in chunks]
    all_text = _plain(
        " ".join(c.chunk.text + " " + c.chunk.section + " " + c.document_title for c in chunks)
    )
    claims = supported = 0
    unsupported: list[str] = []
    for sentence in _sentences(text):
        words = _words(_CITATION.sub(" ", sentence)) - _FILLER
        if len(words) < 3:
            continue
        claims += 1
        cited = valid_citations(sentence, len(chunks))
        source_words = set().union(*(chunk_words[n - 1] for n in cited)) if cited else set()
        if cited and len(words & source_words) / len(words) >= SUPPORT_THRESHOLD:
            supported += 1
        else:
            unsupported.append(sentence.strip())
    unknown = sorted(
        {t for t in _TERM.findall(_CITATION.sub(" ", text)) if t.lower() not in all_text}
    )
    return Grounding(
        score=supported / claims if claims else None,
        claims=claims,
        supported=supported,
        unsupported=unsupported,
        unknown_terms=unknown,
    )


def _plain(text: str) -> str:
    """Lower case, NFKC (ligatures to letters), straight apostrophes."""
    return unicodedata.normalize("NFKC", text).replace("’", "'").lower()


def _stem(word: str) -> str:
    # Crude on purpose: enough to match "regions"/"region", "replicated"/"replicate".
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(_plain(text)) if w not in _STOPWORDS and len(w) > 2}


def _sentences(text: str) -> Iterable[str]:
    for part in _SENTENCE_SPLIT.split(text):
        part = part.strip().lstrip("-*•0123456789. ").strip()
        if part:
            yield part
