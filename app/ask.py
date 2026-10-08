"""
The core Q&A flow: retrieve -> check grounding -> build a prompt -> generate
-> return answer + citations.

Grounding policy: library content and outside knowledge are never blended
into one unlabeled answer.
  - If relevant chunks are found (clear RAG_SIMILARITY_THRESHOLD), the
    answer is built from those excerpts and cited by paper title. The
    model may ALSO add a clearly separate "Beyond your library" section
    using general knowledge — e.g. related methods not in your papers —
    but it's visibly marked as not coming from your library.
  - If nothing relevant is found, we don't just refuse: the model answers
    from general knowledge instead, clearly labeled as such, and suggests
    concrete search terms/directions you can feed into the "Find new
    papers" acquire feature to go get the real sources.
Either way, you always know which parts are verified-from-your-papers and
which aren't — that distinction is the point, not strict refusal itself.
"""
from __future__ import annotations

from app.config import settings
from app.llm import generate
from app.retriever import retrieve

GROUNDED_SYSTEM_PROMPT = (
    "You are a research assistant answering questions using excerpts from the "
    "user's paper library, provided below.\n\n"
    "Primary rule: answer the question using ONLY the excerpts, and when you "
    "state a fact, make clear which paper it came from by title. Do not "
    "present outside knowledge as if it came from the library.\n\n"
    "Optional second part: if there is genuinely relevant general knowledge "
    "that the excerpts don't cover — e.g. a related method, dataset, or fact "
    "you know of that isn't in these papers — you may add it as a clearly "
    "separate section titled exactly \"Beyond your library:\", written so the "
    "user can immediately tell it is NOT from their papers. Never merge this "
    "into the cited part, and omit this section entirely if you have nothing "
    "worth adding or you're not confident about it.\n\n"
    "Be concise and precise — this is for a researcher, not a general audience.\n\n"
    "Recent conversation turns may be included below for context. If the "
    "user's question is a follow-up asking for more detail, clarification, or "
    "elaboration on something already discussed (e.g. 'explain that in detail', "
    "'can you expand on that', 'why is that the case') — rather than refusing "
    "or asking them to rephrase, elaborate using the SAME excerpts that were "
    "retrieved for this turn, and the prior answer as a guide to what 'that' "
    "refers to. Only say the excerpts are insufficient if they genuinely don't "
    "support any further elaboration either."
)

UNGROUNDED_SYSTEM_PROMPT = (
    "The user's local paper library has nothing relevant to this question — no "
    "excerpts are provided. Answer from your own general knowledge instead, but "
    "start your answer with a short clearly-marked line such as \"Nothing in "
    "your library covers this — from general knowledge:\" so the user never "
    "mistakes this for something verified against their papers.\n\n"
    "Then, after the answer, add a section titled exactly \"Search directions:\" "
    "with 2-5 concrete search phrases or topics the user could paste into this "
    "app's 'Find new papers' feature (which searches arXiv) to find real papers "
    "on this — specific enough to be useful (e.g. actual method/dataset names), "
    "not just a restatement of the question.\n\n"
    "Be concise and precise — this is for a researcher, not a general audience."
)

NOT_FOUND_MESSAGE = (
    "I couldn't find anything in your paper library that's closely related to this "
    "question. Try rephrasing, widening the subdomain filter, or add relevant papers "
    "to the library and re-index."
)


def _history_block(history: list[dict] | None) -> str:
    if not history:
        return ""
    # Only the last couple of turns — enough to resolve "that"/"it" in a
    # follow-up, without letting old exchanges dominate the prompt.
    turns = []
    for h in history[-4:]:
        role = "User" if h.get("role") == "user" else "Assistant"
        turns.append(f"{role}: {h.get('content', '')}")
    return "Recent conversation:\n" + "\n".join(turns) + "\n\n"


def _build_grounded_prompt(question: str, chunks: list[dict], history: list[dict] | None = None) -> str:
    context_blocks = []
    for i, c in enumerate(chunks, start=1):
        context_blocks.append(
            f"[{i}] From \"{c['paper_title']}\" (page {c['page']}):\n{c['text']}"
        )
    context = "\n\n".join(context_blocks)

    return (
        f"{_history_block(history)}"
        f"Context excerpts from the paper library:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer using the excerpts above as the primary source, citing papers "
        f"by title. If this question is a follow-up referring back to the "
        f"recent conversation, use it to understand what is being asked, but "
        f"still ground the cited part of your answer in the excerpts."
    )


def _build_ungrounded_prompt(question: str, history: list[dict] | None = None) -> str:
    return (
        f"{_history_block(history)}"
        f"Question: {question}\n\n"
        f"Nothing relevant was found in the user's paper library for this question."
    )


def ask(
    question: str,
    subdomain: str | None = None,
    top_k: int | None = None,
    history: list[dict] | None = None,
) -> dict:
    """Returns {answer, grounded, citations}.

    `grounded` is True only when the answer's primary content came from the
    library (it may still include an unlabeled-as-library "Beyond your
    library" section). When nothing relevant is found, `grounded` is False
    and the answer comes from general knowledge instead of a flat refusal —
    but it's prompted to say so plainly and suggest search directions.

    `history` is an optional list of prior {role, content} turns (e.g. from
    st.session_state.messages) — only used to help resolve vague follow-ups
    like "explain that in detail"; retrieval and grounding still run fresh
    for every call, so a follow-up never pulls in context past turns didn't
    already surface."""
    chunks = retrieve(question, subdomain=subdomain, top_k=top_k)

    if not chunks or chunks[0]["similarity"] < settings.rag_similarity_threshold:
        prompt = _build_ungrounded_prompt(question, history=history)
        answer = generate(prompt, system=UNGROUNDED_SYSTEM_PROMPT)
        return {"answer": answer, "grounded": False, "citations": []}

    # Only pass chunks that clear the floor to the LLM — a couple of
    # weak tail results shouldn't dilute an otherwise strong match.
    good_chunks = [c for c in chunks if c["similarity"] >= settings.rag_similarity_threshold]

    prompt = _build_grounded_prompt(question, good_chunks, history=history)
    answer = generate(prompt, system=GROUNDED_SYSTEM_PROMPT)

    citations = [
        {
            "paper_title": c["paper_title"],
            "page": c["page"],
            "similarity": round(c["similarity"], 3),
            "source_path": c["source_path"],
        }
        for c in good_chunks
    ]

    return {"answer": answer, "grounded": True, "citations": citations}


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "What is hyperspectral imaging?"
    result = ask(q)
    print(result["answer"])
    print(f"\n[grounded={result['grounded']}, {len(result['citations'])} citation(s)]")




# """
# The core Q&A flow: retrieve -> check grounding -> build a grounded
# prompt -> generate -> return answer + citations.

# The guardrail: if nothing retrieved clears RAG_SIMILARITY_THRESHOLD, we
# refuse rather than let the LLM answer from its own general knowledge.
# This is what keeps answers tied to your actual paper library instead of
# the model's pretraining.
# """
# from __future__ import annotations

# from app.config import settings
# from app.llm import generate
# from app.retriever import retrieve

# SYSTEM_PROMPT = (
#     "You are a research assistant answering questions ONLY using the provided "
#     "excerpts from the user's paper library. Do not use outside knowledge. "
#     "If the excerpts don't contain enough information to answer, say so plainly. "
#     "When you state a fact, make clear which paper it came from by title. "
#     "Be concise and precise — this is for a researcher, not a general audience."
# )

# NOT_FOUND_MESSAGE = (
#     "I couldn't find anything in your paper library that's closely related to this "
#     "question. Try rephrasing, widening the subdomain filter, or add relevant papers "
#     "to the library and re-index."
# )


# def _build_prompt(question: str, chunks: list[dict]) -> str:
#     context_blocks = []
#     for i, c in enumerate(chunks, start=1):
#         context_blocks.append(
#             f"[{i}] From \"{c['paper_title']}\" (page {c['page']}):\n{c['text']}"
#         )
#     context = "\n\n".join(context_blocks)
#     return (
#         f"Context excerpts from the paper library:\n\n{context}\n\n"
#         f"Question: {question}\n\n"
#         f"Answer using only the excerpts above, citing papers by title."
#     )


# def ask(question: str, subdomain: str | None = None, top_k: int | None = None) -> dict:
#     """Returns {answer, grounded, citations}."""
#     chunks = retrieve(question, subdomain=subdomain, top_k=top_k)

#     if not chunks or chunks[0]["similarity"] < settings.rag_similarity_threshold:
#         return {"answer": NOT_FOUND_MESSAGE, "grounded": False, "citations": []}

#     # Only pass chunks that clear the floor to the LLM — a couple of
#     # weak tail results shouldn't dilute an otherwise strong match.
#     good_chunks = [c for c in chunks if c["similarity"] >= settings.rag_similarity_threshold]

#     prompt = _build_prompt(question, good_chunks)
#     answer = generate(prompt, system=SYSTEM_PROMPT)

#     citations = [
#         {
#             "paper_title": c["paper_title"],
#             "page": c["page"],
#             "similarity": round(c["similarity"], 3),
#             "source_path": c["source_path"],
#         }
#         for c in good_chunks
#     ]

#     return {"answer": answer, "grounded": True, "citations": citations}
