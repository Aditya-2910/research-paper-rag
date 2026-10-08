"""
On-demand literature review generation for one subdomain. This is NOT
run automatically — only when you explicitly ask for it (via the
Streamlit "Generate literature review" button), since it costs several
LLM calls and you said most of your usage will be ad-hoc Q&A, not
documents.

For now this saves a local Markdown file. Once Google OAuth + the MCP
server are set up (Phase B), this same synthesis gets pushed to a Google
Doc instead — the retrieval/synthesis logic here doesn't change, only
where the output goes.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from app.config import settings
from app.llm import generate
from app.retriever import list_papers
from app.vectorstore import get_collection

PER_PAPER_SYSTEM_PROMPT = (
    "You summarize a single research paper for a literature review, based only on "
    "the excerpt provided. Write 2-4 sentences covering: what problem it addresses, "
    "its core method, and any dataset/results mentioned in the excerpt. Be factual "
    "and concise. If the excerpt is insufficient, say what's missing rather than "
    "guessing."
)

SYNTHESIS_SYSTEM_PROMPT = (
    "You write the overview section of a literature review. Given per-paper "
    "summaries, identify common themes, methods, and datasets across them, and "
    "note any notable differences in approach. Write 1-2 short paragraphs. Be "
    "specific — name papers by title when pointing out a theme or contrast."
)


def _paper_context(source_path: str, max_chars: int = 2500) -> str:
    """Grabs the earliest chunks of a paper (by page) as a stand-in for
    its abstract/intro — good enough for a summary without needing full
    section detection."""
    collection = get_collection()
    results = collection.get(
        where={"source_path": source_path}, include=["documents", "metadatas"]
    )
    pairs = list(zip(results["documents"], results["metadatas"]))
    pairs.sort(key=lambda p: (p[1].get("page", 0),))

    context = ""
    for text, _ in pairs:
        if len(context) >= max_chars:
            break
        context += text + "\n"
    return context[:max_chars]


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_")


def generate_review(subdomain: str) -> dict:
    """Returns {path, content, paper_count}."""
    papers = list_papers(subdomain=subdomain)
    if not papers:
        return {"path": None, "content": None, "paper_count": 0}

    per_paper_summaries = []
    for paper in papers:
        context = _paper_context(paper["source_path"])
        prompt = f"Paper title: {paper['paper_title']}\n\nExcerpt:\n{context}\n\nSummarize."
        summary = generate(prompt, system=PER_PAPER_SYSTEM_PROMPT)
        per_paper_summaries.append({"title": paper["paper_title"], "summary": summary})

    synthesis_input = "\n\n".join(
        f"- {p['title']}: {p['summary']}" for p in per_paper_summaries
    )
    overview = generate(
        f"Per-paper summaries:\n\n{synthesis_input}\n\nWrite the overview.",
        system=SYNTHESIS_SYSTEM_PROMPT,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    title = f"Literature Review: {subdomain}"

    lines = [f"# {title}", "", f"*Generated {timestamp} UTC — {len(papers)} papers*", ""]
    lines += ["## Overview", "", overview, ""]
    lines += ["## Papers", ""]
    for p in per_paper_summaries:
        lines += [f"### {p['title']}", "", p["summary"], ""]

    content = "\n".join(lines)

    os.makedirs(settings.reports_dir, exist_ok=True)
    filename = f"{_slugify(subdomain)}_{timestamp}.md"
    path = os.path.join(settings.reports_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return {"path": path, "content": content, "paper_count": len(papers)}
