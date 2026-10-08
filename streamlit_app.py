"""
AROS — chat UI over your local paper library.

Run:
    streamlit run streamlit_app.py
"""
# import streamlit as st

# from app.acquire import download_selected, search_and_judge
# from app.ask import ask
# from app.indexer import library_status, run as run_indexer
# from app.report import generate_review
import glob
import os
import json

import streamlit as st

from app.acquire import download_selected, search_and_judge
from app.ask import ask
from app.config import settings
from app.digest import run_digest
from app.indexer import library_status, run as run_indexer
from app.report import generate_review

st.set_page_config(page_title="AROS", page_icon="📚", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {role, content, citations?}

# ---------- Sidebar ----------
with st.sidebar:
    st.title("📚 AROS")
    st.caption("Research assistant over your local paper library")

    status = library_status()
    st.subheader("Library")
    if status:
        for subdomain, count in sorted(status.items()):
            st.write(f"**{subdomain}** — {count} paper(s)")
    else:
        st.write("No papers found yet. Drop PDFs into `papers/<subdomain>/` and re-index.")

    if st.button("🔄 Re-index papers", use_container_width=True):
        with st.spinner("Indexing..."):
            summary = run_indexer(verbose=False)
        st.success(
            f"Added {summary['added']}, updated {summary['updated']}, "
            f"removed {summary['removed']}, skipped {summary['skipped']}"
        )
        st.rerun()

    st.divider()

    st.subheader("Scope")
    subdomain_options = ["All"] + sorted(status.keys())
    selected_subdomain = st.selectbox("Limit to subdomain", subdomain_options)

    st.divider()

    st.subheader("Literature review")
    st.caption("Generates an on-demand summary — not automatic, since it costs several LLM calls.")
    review_target = st.selectbox(
        "Subdomain to review", sorted(status.keys()) if status else [], key="review_target"
    )
    if status and st.button("📝 Generate literature review", use_container_width=True):
        with st.spinner(f"Reviewing {review_target}..."):
            result = generate_review(review_target)
        if result["paper_count"] == 0:
            st.warning("No papers found in that subdomain.")
        else:
            st.success(f"Saved to `{result['path']}`")
            with st.expander("Preview", expanded=True):
                st.markdown(result["content"])
            st.download_button(
                "Download .md",
                data=result["content"],
                file_name=result["path"].split("/")[-1],
                use_container_width=True,
            )

    st.divider()


    #---------- weekly digest ----------
    # st.subheader("New papers digest")
    # st.caption(
    #     "Scans every folder's topic against arXiv (same relevance judgment as "
    #     "'Find new papers' below) and reports anything new — nothing downloads "
    #     "here. Meant to run weekly on its own (once you set up the systemd "
    #     "timer); click any time to run it now instead."
    # )
    # if st.button("🗞️ Check for new papers now", use_container_width=True):
    #     with st.spinner("Scanning all subdomains against arXiv (can take a few minutes)..."):
    #         digest_result = run_digest()
    #     if digest_result["new_count"] == 0:
    #         st.info("No new relevant papers found since the last digest.")
    #     else:
    #         st.success(f"{digest_result['new_count']} new candidate(s) found.")
    #         with open(digest_result["path"]) as f:
    #             digest_content = f.read()
    #         with st.expander("View digest", expanded=True):
    #             st.markdown(digest_content)
    #         st.download_button(
    #             "Download digest .md",
    #             data=digest_content,
    #             file_name=os.path.basename(digest_result["path"]),
    #             use_container_width=True,
    #         )

    # existing_digests = sorted(
    #     glob.glob(os.path.join(settings.reports_dir, "new_papers_digest_*.md"))
    # )
    # if existing_digests:
    #     latest = existing_digests[-1]
    #     with st.expander(f"📁 Latest saved digest ({os.path.basename(latest)})"):
    #         st.markdown(open(latest).read())

    # st.divider()
    st.subheader("New papers digest")
    st.caption(
        "Scans every folder's topic against arXiv (same relevance judgment as "
        "'Find new papers' below) and reports anything new — nothing downloads "
        "automatically. Review below and download only the ones you want, "
        "into whichever folder you choose (not necessarily the suggested one)."
    )

    if st.button("🗞️ Check for new papers now", use_container_width=True):
        with st.spinner("Scanning all subdomains against arXiv (can take a few minutes)..."):
            digest_result = run_digest()
        st.session_state.digest_candidates = digest_result["candidates"]
        if digest_result["new_count"] == 0:
            st.info("No new relevant papers found since the last digest.")

    # Pick up the latest digest's candidates even without clicking the
    # button — covers a digest produced earlier by the systemd timer.
    if "digest_candidates" not in st.session_state:
        existing_jsons = sorted(
            glob.glob(os.path.join(settings.reports_dir, "new_papers_digest_*.json"))
        )
        if existing_jsons:
            with open(existing_jsons[-1]) as f:
                st.session_state.digest_candidates = json.load(f)["candidates"]

    digest_candidates = st.session_state.get("digest_candidates")
    if digest_candidates:
        st.caption(f"{len(digest_candidates)} candidate(s) in the latest digest.")
        existing_folders = sorted(status.keys())
        digest_selections = []

        for i, c in enumerate(digest_candidates):
            checked = st.checkbox(
                f"{c['title']}  _(from: {c['source_folder']})_",
                value=True,
                key=f"dig_check_{i}",
            )
            st.caption(c["reason"])

            folder_options = existing_folders + ["+ new folder"]
            suggested = c.get("suggested_folder")
            default_index = (
                folder_options.index(suggested)
                if suggested in folder_options
                else len(folder_options) - 1
            )
            folder_choice = st.selectbox(
                "Folder", folder_options, index=default_index, key=f"dig_folder_{i}"
            )
            if folder_choice == "+ new folder":
                folder_name = st.text_input(
                    "New folder name", value=suggested or "general", key=f"dig_newfolder_{i}"
                )
            else:
                folder_name = folder_choice

            if checked:
                digest_selections.append(
                    {
                        "arxiv_id": c["arxiv_id"],
                        "title": c["title"],
                        "pdf_url": c["pdf_url"],
                        "folder": folder_name,
                    }
                )
            st.divider()

        if digest_selections and st.button(
            f"⬇️ Download {len(digest_selections)} selected from digest", use_container_width=True
        ):
            with st.spinner("Downloading and indexing..."):
                digest_download_results = download_selected(digest_selections)
                run_indexer(verbose=False)
            for r in digest_download_results:
                if r["status"] == "downloaded":
                    st.success(f"Saved: {r['title']} → {r['folder']}/")
                else:
                    st.error(f"Failed: {r['title']} ({r['status']})")
            st.session_state.digest_candidates = None
            st.rerun()

    st.divider()


    st.subheader("Find new papers")
    st.caption(
        "Searches arXiv for a topic, has the LLM judge each candidate's relevance "
        "to THAT topic, and suggests a folder. Nothing downloads until you confirm."
    )

    topic_input = st.text_input("Topic or idea", key="acquire_topic")
    if st.button("🔎 Search & judge", use_container_width=True) and topic_input.strip():
        with st.spinner("Searching arXiv and judging relevance (this takes a minute)..."):
            st.session_state.acquire_candidates = search_and_judge(topic_input.strip())

    candidates = st.session_state.get("acquire_candidates")
    if candidates:
        st.caption(f"{len(candidates)} candidate(s) found. Review and confirm below.")
        existing_folders = sorted(status.keys())
        selections_to_download = []

        for i, c in enumerate(candidates):
            if c["already_in_library"]:
                st.write(f"✅ *(already in library)* {c['title']}")
                continue

            checked = st.checkbox(
                f"{'✅' if c['relevant'] else '⚠️'} {c['title']}",
                value=c["relevant"],
                key=f"acq_check_{i}",
            )
            st.caption(c["reason"])

            folder_options = existing_folders + ["+ new folder"]
            suggested = c["suggested_folder"]
            default_index = (
                folder_options.index(suggested)
                if suggested in folder_options
                else len(folder_options) - 1
            )
            folder_choice = st.selectbox(
                "Folder", folder_options, index=default_index, key=f"acq_folder_{i}"
            )
            if folder_choice == "+ new folder":
                folder_name = st.text_input(
                    "New folder name", value=suggested or "general", key=f"acq_newfolder_{i}"
                )
            else:
                folder_name = folder_choice

            if checked:
                selections_to_download.append(
                    {
                        "arxiv_id": c["arxiv_id"],
                        "title": c["title"],
                        "pdf_url": c["pdf_url"],
                        "folder": folder_name,
                    }
                )
            st.divider()

        if selections_to_download and st.button(
            f"⬇️ Download {len(selections_to_download)} selected", use_container_width=True
        ):
            with st.spinner("Downloading and indexing..."):
                download_results = download_selected(selections_to_download)
                run_indexer(verbose=False)
            for r in download_results:
                if r["status"] == "downloaded":
                    st.success(f"Saved: {r['title']} → {r['folder']}/")
                else:
                    st.error(f"Failed: {r['title']} ({r['status']})")
            st.session_state.acquire_candidates = None
            st.rerun()

# ---------- Main chat ----------
st.header("Ask your paper library")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("citations"):
            with st.expander(f"Sources ({len(msg['citations'])})"):
                for c in msg["citations"]:
                    st.write(
                        f"**{c['paper_title']}** — page {c['page']} "
                        f"(similarity {c['similarity']})"
                    )

question = st.chat_input("Ask a question about your papers...")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # with st.chat_message("assistant"):
    #     with st.spinner("Thinking..."):
    #         result = ask(question, subdomain=selected_subdomain)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            # Exclude the just-appended user message itself — ask() gets the
            # current question separately — so pass everything before it.
            prior_history = st.session_state.messages[:-1]
            result = ask(question, subdomain=selected_subdomain, history=prior_history)
        st.markdown(result["answer"])
        if result["citations"]:
            with st.expander(f"Sources ({len(result['citations'])})"):
                for c in result["citations"]:
                    st.write(
                        f"**{c['paper_title']}** — page {c['page']} "
                        f"(similarity {c['similarity']})"
                    )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result["answer"],
            "citations": result["citations"],
        }
    )
