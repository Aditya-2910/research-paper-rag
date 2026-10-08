"""
Indexes everything under papers/<subdomain>/*.pdf into the Chroma
collection: extracts text per page, chunks with a section-agnostic but
reliable recursive splitter, embeds, and upserts.

Keeps a manifest (index/manifest.json) mapping file path -> content hash,
so re-running only touches files that are new or changed, and removes
anything whose PDF got deleted from the folder. This matters once your
library has hundreds of papers — you don't want to re-embed everything
every time you add one file.

Run:
    python -m app.indexer
"""
from __future__ import annotations

import hashlib
import json
import os

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.config import settings
from app.embedder import embed_texts
from app.vectorstore import get_collection

MANIFEST_PATH = os.path.join("index", "manifest.json")


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> dict[str, str]:
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            return json.load(f)
    return {}


def _save_manifest(manifest: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def _discover_pdfs() -> dict[str, str]:
    """Returns {file_path: subdomain} for every PDF under papers/<subdomain>/."""
    found = {}
    if not os.path.isdir(settings.papers_dir):
        return found
    for subdomain in sorted(os.listdir(settings.papers_dir)):
        subdomain_path = os.path.join(settings.papers_dir, subdomain)
        if not os.path.isdir(subdomain_path):
            continue
        for fname in sorted(os.listdir(subdomain_path)):
            if fname.lower().endswith(".pdf"):
                found[os.path.join(subdomain_path, fname)] = subdomain
    return found


def _paper_title(reader: PdfReader, file_path: str) -> str:
    try:
        title = reader.metadata.title if reader.metadata else None
        if title and title.strip():
            return title.strip()
    except Exception:
        pass
    return os.path.splitext(os.path.basename(file_path))[0]


def _extract_pages(file_path: str) -> tuple[str, list[str]]:
    """Returns (title, [text_per_page])."""
    reader = PdfReader(file_path)
    title = _paper_title(reader, file_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return title, pages


def _chunk_paper(file_path: str, subdomain: str) -> tuple[list[str], list[dict], list[str]]:
    """Returns (texts, metadatas, ids) for one paper's chunks."""
    title, pages = _extract_pages(file_path)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    texts, metadatas, ids = [], [], []
    file_id = hashlib.sha256(file_path.encode()).hexdigest()[:16]

    for page_num, page_text in enumerate(pages, start=1):
        if not page_text.strip():
            continue
        page_chunks = splitter.split_text(page_text)
        for chunk_idx, chunk_text in enumerate(page_chunks):
            texts.append(chunk_text)
            metadatas.append(
                {
                    "subdomain": subdomain,
                    "paper_title": title,
                    "source_path": file_path,
                    "page": page_num,
                }
            )
            ids.append(f"{file_id}__{page_num}__{chunk_idx}")

    return texts, metadatas, ids


def _remove_file_from_collection(collection, file_path: str) -> None:
    collection.delete(where={"source_path": file_path})


def run(verbose: bool = True) -> dict:
    """Indexes the paper library. Returns a summary dict."""
    collection = get_collection()
    manifest = _load_manifest()
    current_files = _discover_pdfs()

    added, updated, removed, skipped = 0, 0, 0, 0

    # Handle deletions: files in the manifest but no longer on disk.
    for old_path in list(manifest.keys()):
        if old_path not in current_files:
            _remove_file_from_collection(collection, old_path)
            del manifest[old_path]
            removed += 1
            if verbose:
                print(f"Removed (deleted from disk): {old_path}")

    # Handle new/changed files.
    for file_path, subdomain in current_files.items():
        new_hash = _file_hash(file_path)
        old_hash = manifest.get(file_path)

        if old_hash == new_hash:
            skipped += 1
            continue

        is_update = old_hash is not None
        if is_update:
            _remove_file_from_collection(collection, file_path)  # re-embed cleanly

        texts, metadatas, ids = _chunk_paper(file_path, subdomain)
        if texts:
            embeddings = embed_texts(texts)
            collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

        manifest[file_path] = new_hash
        if is_update:
            updated += 1
            if verbose:
                print(f"Updated: {file_path} ({len(texts)} chunks)")
        else:
            added += 1
            if verbose:
                print(f"Added: {file_path} ({len(texts)} chunks)")

    _save_manifest(manifest)

    summary = {"added": added, "updated": updated, "removed": removed, "skipped": skipped}
    if verbose:
        print(f"\nDone. {summary}")
    return summary


def library_status() -> dict[str, int]:
    """Returns {subdomain: paper_count} for the sidebar status display."""
    current_files = _discover_pdfs()
    counts: dict[str, int] = {}
    for _, subdomain in current_files.items():
        counts[subdomain] = counts.get(subdomain, 0) + 1
    return counts


if __name__ == "__main__":
    run()
