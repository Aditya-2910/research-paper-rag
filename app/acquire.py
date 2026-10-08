"""
Topic-driven paper acquisition: search arXiv for a topic, have the LLM
judge each candidate's relevance to THAT specific topic (not a fixed
bulk classifier — this is one relevance call per candidate, scoped to
exactly what you asked, which is why it doesn't suffer the precision
problems a blanket keyword/category fetch does), suggest which existing
folder it belongs in (or propose a new one), and only download once you
confirm.

Two-phase by design — search_and_judge() never writes anything to disk,
only download_selected() does, after you've reviewed the candidates:

    candidates = search_and_judge("domain adaptation for HSI classification")
    # ... you look at candidates, pick which ones + folders ...
    results = download_selected([{...}, ...])

Run standalone for a quick check:
    python -m app.acquire "domain adaptation for hyperspectral classification"
"""
from __future__ import annotations

import os
import re
import time

import feedparser
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.llm import generate

ARXIV_API_URL = "https://export.arxiv.org/api/query"

STOPWORDS = {
    "a", "an", "the", "of", "for", "in", "on", "with", "using", "to", "and",
    "or", "is", "are", "paper", "papers", "method", "methods", "approach",
    "approaches", "based", "via", "that", "this", "idea", "like",
}

RELEVANCE_SYSTEM = (
    "You judge whether a paper is relevant to a specific research topic, based "
    "only on its title and abstract. Answer in exactly this format:\n"
    "RELEVANT: yes or no\n"
    "REASON: one short sentence"
)

FOLDER_SYSTEM = (
    "You file a paper into the most fitting folder from a given list, or propose "
    "a new short folder name (lowercase, underscores, no spaces) if none fit well. "
    "Answer in exactly this format:\n"
    "FOLDER: <existing folder name from the list, OR NEW:<new_folder_name>>"
)


def _slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len] or "paper"


def _build_query_terms(topic: str) -> str:
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", topic.lower()) if w not in STOPWORDS]
    if not words:
        words = topic.split() or ["research"]
    return " AND ".join(f"all:{w}" for w in words[:8])  # cap to keep the query sane


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _fetch_arxiv(search_query: str, max_results: int) -> feedparser.FeedParserDict:
    params = {
        "search_query": search_query,
        "sortBy": "relevance",
        "sortOrder": "descending",
        "start": 0,
        "max_results": max_results,
    }
    resp = httpx.get(ARXIV_API_URL, params=params, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return feedparser.parse(resp.text)


def _parse_entry(entry) -> dict:
    arxiv_id = entry.id.split("/abs/")[-1]
    arxiv_id = arxiv_id.split("v")[0] if "v" in arxiv_id.split("/")[-1] else arxiv_id
    pdf_url = next(
        (l.href for l in entry.links if getattr(l, "type", "") == "application/pdf"),
        entry.id.replace("/abs/", "/pdf/"),
    )
    return {
        "arxiv_id": arxiv_id,
        "title": " ".join(entry.title.split()),
        "abstract": " ".join(entry.summary.split()),
        "authors": ", ".join(a.name for a in entry.authors),
        "pdf_url": pdf_url,
    }


def _existing_folders() -> list[str]:
    if not os.path.isdir(settings.papers_dir):
        return []
    return sorted(
        d for d in os.listdir(settings.papers_dir)
        if os.path.isdir(os.path.join(settings.papers_dir, d))
    )


def _already_downloaded(arxiv_id: str) -> bool:
    if not os.path.isdir(settings.papers_dir):
        return False
    for _, _, files in os.walk(settings.papers_dir):
        if any(f.startswith(arxiv_id) for f in files):
            return True
    return False


def _judge_relevance(topic: str, candidate: dict) -> dict:
    prompt = (
        f"Topic: {topic}\n\n"
        f"Paper title: {candidate['title']}\n"
        f"Abstract: {candidate['abstract']}\n\n"
        f"Is this paper relevant to the topic?"
    )
    response = generate(prompt, system=RELEVANCE_SYSTEM)
    relevant = bool(re.search(r"RELEVANT:\s*yes", response, re.IGNORECASE))
    reason_match = re.search(r"REASON:\s*(.+)", response, re.IGNORECASE)
    reason = reason_match.group(1).strip() if reason_match else response.strip()[:200]
    return {"relevant": relevant, "reason": reason}


def _suggest_folder(topic: str, candidate: dict, existing_folders: list[str]) -> str:
    folder_list = ", ".join(existing_folders) if existing_folders else "(none yet)"
    prompt = (
        f"Topic: {topic}\n"
        f"Paper title: {candidate['title']}\n"
        f"Abstract: {candidate['abstract']}\n\n"
        f"Existing folders: {folder_list}\n\n"
        f"Which folder does this paper belong in?"
    )
    response = generate(prompt, system=FOLDER_SYSTEM)
    match = re.search(r"FOLDER:\s*(.+)", response, re.IGNORECASE)
    raw = match.group(1).strip() if match else "general"

    if raw.upper().startswith("NEW:"):
        return _slugify(raw.split(":", 1)[1])

    # If the model echoed something close to an existing folder name,
    # snap to it exactly (case-insensitive) rather than creating a
    # near-duplicate folder.
    for folder in existing_folders:
        if folder.lower() == raw.lower():
            return folder
    return _slugify(raw) if raw else "general"


def search_and_judge(topic: str, max_candidates: int | None = None) -> list[dict]:
    """Searches arXiv, judges each candidate's relevance to `topic`, and
    suggests a folder — but does NOT download anything. Returns a list
    of candidate dicts for review before download."""
    max_candidates = max_candidates or settings.acquire_max_candidates
    query = _build_query_terms(topic)
    feed = _fetch_arxiv(query, max_results=max_candidates)
    existing_folders = _existing_folders()

    results = []
    for entry in feed.entries:
        candidate = _parse_entry(entry)
        candidate["already_in_library"] = _already_downloaded(candidate["arxiv_id"])

        judgment = _judge_relevance(topic, candidate)
        candidate.update(judgment)

        if not candidate["already_in_library"]:
            candidate["suggested_folder"] = _suggest_folder(topic, candidate, existing_folders)
        else:
            candidate["suggested_folder"] = None

        results.append(candidate)

    return results


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _download_pdf(pdf_url: str, dest_path: str) -> None:
    resp = httpx.get(pdf_url, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    tmp = dest_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(resp.content)
    os.replace(tmp, dest_path)  # atomic-ish: no half-written file left on crash


def download_selected(selections: list[dict]) -> list[dict]:
    """selections: list of {arxiv_id, title, pdf_url, folder}. Downloads
    each into papers/<folder>/, creating the folder if it's new. Returns
    one status dict per item — never raises on an individual failure, so
    one bad download doesn't stop the rest."""
    results = []
    for i, sel in enumerate(selections):
        folder_path = os.path.join(settings.papers_dir, sel["folder"])
        os.makedirs(folder_path, exist_ok=True)

        filename = f"{sel['arxiv_id']}_{_slugify(sel['title'])}.pdf"
        dest_path = os.path.join(folder_path, filename)

        try:
            _download_pdf(sel["pdf_url"], dest_path)
            results.append({**sel, "status": "downloaded", "path": dest_path})
        except Exception as e:
            results.append({**sel, "status": f"failed: {e}", "path": None})

        if i < len(selections) - 1:
            time.sleep(settings.arxiv_request_delay_seconds)  # be polite to arXiv

    return results


if __name__ == "__main__":
    import sys

    topic_arg = " ".join(sys.argv[1:]) or "hyperspectral image classification"
    print(f"Searching for: {topic_arg}\n")
    for c in search_and_judge(topic_arg):
        tag = "RELEVANT" if c["relevant"] else "skip"
        print(f"[{tag}] {c['title']}")
        print(f"   reason: {c['reason']}")
        if c["already_in_library"]:
            print("   (already in library)")
        else:
            print(f"   suggested folder: {c['suggested_folder']}")
        print()
