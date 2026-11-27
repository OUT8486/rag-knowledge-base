"""Budget source text and reject model citations outside the supplied evidence."""

import re

from app.services.llm import NO_EVIDENCE

CONTEXT_CHARS = 3000


def pack_sources(chunks):
    """Only excerpts actually sent to the model get a reference number."""
    remaining, sources = CONTEXT_CHARS, []
    for chunk in chunks:
        if remaining <= 0:
            break
        text = chunk["text"][:remaining].strip()
        if text:
            sources.append({**chunk, "text": text, "source_id": f"S{len(sources) + 1}"})
            remaining -= len(text)
    return sources


def checked_answer(answer, sources):
    cites = set(re.findall(r"\[(S[0-9]+)\]", answer))
    allowed = {s["source_id"] for s in sources}
    if answer == NO_EVIDENCE or not cites or not cites.issubset(allowed):
        return {"answer": NO_EVIDENCE, "sources": []}
    return {"answer": answer, "sources": [s for s in sources if s["source_id"] in cites]}
