
"""
Weekly "what's new" scan — NOT an auto-downloader. For each existing
papers/<subdomain>/ folder, searches arXiv using that folder's topic,
judges relevance (reusing app.acquire), and writes:
  - a markdown digest for reading (reports/new_papers_digest_<date>.md)
  - a JSON sidecar with the structured candidate list
    (reports/new_papers_digest_<date>.json), so the UI can rebuild
    per-paper checkboxes + folder pickers later and download only the
    ones you pick, into whichever folder you choose — not necessarily
    the suggested one.

Nothing is downloaded here — same human-in-the-loop guarantee as the
rest of the acquire flow.

Run manually:
    python -m app.digest

Each folder can optionally have a papers/<folder>/.topic.txt file with
a one-line topic description for a better search query than the raw
folder name.
"""
from __future__ import annotations

import json
import os
from datetime import date

from app.acquire import _existing_folders, search_and_judge
from app.config import settings

SEEN_PATH = os.path.join(os.path.dirname(settings.chroma_dir), "digest_seen.json")


def _topic_for_folder(folder: str) -> str:
    topic_file = os.path.join(settings.papers_dir, folder, ".topic.txt")
    if os.path.isfile(topic_file):
        text = open(topic_file).read().strip()
        if text:
            return text
    return folder.replace("_", " ")


def _load_seen() -> dict:
    if os.path.isfile(SEEN_PATH):
        with open(SEEN_PATH) as f:
            return json.load(f)
    return {}


def _save_seen(seen: dict) -> None:
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w") as f:
        json.dump(seen, f, indent=2)


def run_digest(max_candidates_per_folder: int | None = None) -> dict:
    """Returns {path, json_path, new_count, candidates}.
    path/json_path are None if nothing new was found — no empty files
    get written in that case. candidates is a flat list of dicts
    (arxiv_id, title, pdf_url, reason, suggested_folder, source_folder)
    ready to feed into app.acquire.download_selected() after you pick
    which ones and which folder."""
    folders = _existing_folders()
    seen = _load_seen()
    today = date.today().isoformat()

    sections = []
    all_fresh = []

    for folder in folders:
        topic = _topic_for_folder(folder)
        candidates = search_and_judge(
            topic, max_candidates=max_candidates_per_folder or settings.acquire_max_candidates
        )
        folder_seen = seen.setdefault(folder, {})

        fresh = []
        # for c in candidates:
        #     if c["already_in_library"] or c["arxiv_id"] in folder_seen:
        #         continue
        #     folder_seen[c["arxiv_id"]] = today  # mark seen either way, so we
        #     if c["relevant"]:                    # never re-report the same
        #         fresh.append(c)                  # paper even if it stays irrelevant
        for c in candidates:
            if c["already_in_library"]:
                continue  # already in your library — nothing to report

            if c["relevant"]:
                # Keep resurfacing a relevant-but-undownloaded paper on every
                # run. It should stop appearing only once you actually
                # download it (caught by already_in_library above) — not
                # just because an earlier digest already mentioned it.
                fresh.append(c)
            else:
                # Irrelevant candidates ARE worth suppressing after the
                # first time, so the digest doesn't keep repeating the same
                # non-matching paper every week.
                if c["arxiv_id"] in folder_seen:
                    continue
                folder_seen[c["arxiv_id"]] = today

        if fresh:
            lines = [f"### {folder}", f"_topic used: \"{topic}\"_", ""]
            for c in fresh:
                lines.append(f"- **{c['title']}** (arXiv:{c['arxiv_id']})")
                lines.append(f"  - {c['reason']}")
                lines.append(f"  - suggested folder: `{c['suggested_folder']}`")
                lines.append(f"  - {c['pdf_url']}")
                all_fresh.append(
                    {
                        "arxiv_id": c["arxiv_id"],
                        "title": c["title"],
                        "pdf_url": c["pdf_url"],
                        "reason": c["reason"],
                        "suggested_folder": c["suggested_folder"],
                        "source_folder": folder,
                    }
                )
            sections.append("\n".join(lines))

    _save_seen(seen)

    if not sections:
        return {"path": None, "json_path": None, "new_count": 0, "candidates": []}

    os.makedirs(settings.reports_dir, exist_ok=True)

    md_content = (
        f"# New papers digest — {today}\n\n"
        + "\n\n".join(sections)
        + "\n\n---\nReview and download selected papers from the app's "
        "\"New papers digest\" section — you choose which ones and which folder.\n"
    )
    md_path = os.path.join(settings.reports_dir, f"new_papers_digest_{today}.md")
    with open(md_path, "w") as f:
        f.write(md_content)

    json_path = os.path.join(settings.reports_dir, f"new_papers_digest_{today}.json")
    with open(json_path, "w") as f:
        json.dump({"date": today, "candidates": all_fresh}, f, indent=2)

    return {
        "path": md_path,
        "json_path": json_path,
        "new_count": len(all_fresh),
        "candidates": all_fresh,
    }


if __name__ == "__main__":
    result = run_digest()
    if result["new_count"] == 0:
        print("No new relevant papers found since last digest.")
    else:
        print(f"{result['new_count']} new candidate(s) found. Saved to {result['path']}")



# """
# Weekly "what's new" scan — NOT an auto-downloader. For each existing
# papers/<subdomain>/ folder, searches arXiv using that folder's topic,
# judges relevance (reusing app.acquire), and writes a digest markdown
# file listing only genuinely new, relevant, not-yet-seen candidates.
# Nothing is downloaded here — you review the digest and use the
# Streamlit "Find new papers" box (or app.acquire directly) to confirm
# and download whichever ones you want, same human-in-the-loop guarantee
# as before.

# Run manually:
#     python -m app.digest

# Each folder can optionally have a papers/<folder>/.topic.txt file with
# a one-line topic description (e.g. "domain adaptation for hyperspectral
# image classification") for a better search query than the raw folder
# name. Without it, the folder name (underscores -> spaces) is used.
# """
# from __future__ import annotations

# import json
# import os
# from datetime import date

# from app.acquire import _existing_folders, search_and_judge
# from app.config import settings

# SEEN_PATH = os.path.join(os.path.dirname(settings.chroma_dir), "digest_seen.json")


# def _topic_for_folder(folder: str) -> str:
#     topic_file = os.path.join(settings.papers_dir, folder, ".topic.txt")
#     if os.path.isfile(topic_file):
#         text = open(topic_file).read().strip()
#         if text:
#             return text
#     return folder.replace("_", " ")


# def _load_seen() -> dict:
#     if os.path.isfile(SEEN_PATH):
#         with open(SEEN_PATH) as f:
#             return json.load(f)
#     return {}


# def _save_seen(seen: dict) -> None:
#     os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
#     with open(SEEN_PATH, "w") as f:
#         json.dump(seen, f, indent=2)


# def run_digest(max_candidates_per_folder: int | None = None) -> dict:
#     """Returns {path, new_count}. path is None if nothing new was found —
#     no empty file gets written in that case."""
#     folders = _existing_folders()
#     seen = _load_seen()
#     today = date.today().isoformat()

#     sections = []
#     total_new = 0

#     for folder in folders:
#         topic = _topic_for_folder(folder)
#         candidates = search_and_judge(
#             topic, max_candidates=max_candidates_per_folder or settings.acquire_max_candidates
#         )
#         folder_seen = seen.setdefault(folder, {})

#         fresh = []
#         for c in candidates:
#             if c["already_in_library"] or c["arxiv_id"] in folder_seen:
#                 continue
#             folder_seen[c["arxiv_id"]] = today  # mark seen either way, so we
#             if c["relevant"]:                    # never re-report the same
#                 fresh.append(c)                  # paper even if it stays irrelevant

#         if fresh:
#             total_new += len(fresh)
#             lines = [f"### {folder}", f"_topic used: \"{topic}\"_", ""]
#             for c in fresh:
#                 lines.append(f"- **{c['title']}** (arXiv:{c['arxiv_id']})")
#                 lines.append(f"  - {c['reason']}")
#                 lines.append(f"  - suggested folder: `{c['suggested_folder']}`")
#                 lines.append(f"  - {c['pdf_url']}")
#             sections.append("\n".join(lines))

#     _save_seen(seen)

#     if not sections:
#         return {"path": None, "new_count": 0}

#     content = (
#         f"# New papers digest — {today}\n\n"
#         + "\n\n".join(sections)
#         + "\n\n---\nOpen the app's \"Find new papers\" box with the topic shown "
#         "above (or just the folder name) to review and download any of these.\n"
#     )
#     os.makedirs(settings.reports_dir, exist_ok=True)
#     path = os.path.join(settings.reports_dir, f"new_papers_digest_{today}.md")
#     with open(path, "w") as f:
#         f.write(content)

#     return {"path": path, "new_count": total_new}


# if __name__ == "__main__":
#     result = run_digest()
#     if result["new_count"] == 0:
#         print("No new relevant papers found since last digest.")
#     else:
#         print(f"{result['new_count']} new candidate(s) found. Saved to {result['path']}")