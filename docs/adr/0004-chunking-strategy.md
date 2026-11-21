# ADR 0004: Chunking strategy

**Status:** Accepted, 2026-11-19. Revisit in Phase 3 with evaluation results.

## Context

Documents must be split into pieces small enough to embed and to place in a
prompt, and large enough to make sense on their own. The AWS Well-Architected
PDFs are long (hundreds of pages), structured by pillar and best practice, and
answers must cite a page.

## Decision

- Split **within sections** taken from the PDF's table of contents (depth 2).
  A chunk never spans two sections.
- Use LangChain's `RecursiveCharacterTextSplitter`: paragraph breaks first, then
  lines, sentences, words.
- **1,200 characters** per chunk (about 300 tokens), **200 characters** of overlap.
- Track each chunk's start offset and map it to the page it starts on.
- Drop fragments under 40 characters.
- A fingerprint of the text plus the chunking settings decides whether a document
  must be re-processed.

## Why

- Section boundaries are topic boundaries; mixing two topics in one vector
  blurs both.
- About 300 tokens holds one best practice with its context; 4 chunks fit easily
  in a small model's context window with room for the answer.
- Overlap keeps a sentence cut at a boundary whole in at least one chunk.
- Characters rather than tokens: no tokenizer dependency, and the sizes differ
  between providers anyway. Roughly 4 characters per token for English.

**Rejected:** fixed-size splitting (cuts mid-sentence), one chunk per page (pages
are layout, not meaning), semantic chunking with embeddings (embeds the corpus
twice; worth testing only once evaluation exists).

## Consequences

- Chunk size is a guess until Phase 3 measures retrieval quality at 800, 1,200
  and 2,000 characters.
- Changing the settings re-embeds every document (by design: the fingerprint
  includes them). On Bedrock that has a cost, so size changes are deliberate.
- Very short sections become one small chunk; very long ones become many.
