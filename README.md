# AROS — local paper library assistant

Chat with your own PDF library (organized by subdomain folders), grounded
in your papers only — with a guardrail that refuses to answer rather than
guess if nothing relevant is found. Generate an on-demand literature
review for any subdomain, saved as Markdown (Google Docs export is a
planned Phase B addition). Also finds and downloads new papers by topic,
with LLM relevance judgment and folder suggestion — nothing downloads
until you review and confirm.

## Structure

```
papers/<subdomain>/*.pdf   <- put your PDFs here, organized by subdomain
index/                      <- Chroma vector store (auto-created)
reports/                    <- generated literature reviews land here
app/
  config.py        settings from .env
  embedder.py        sentence-transformers wrapper (bge-large)
  vectorstore.py    Chroma collection (cosine similarity)
  indexer.py         scans papers/, chunks, embeds, upserts (skips unchanged files)
  retriever.py        queries the Chroma collection
  llm.py                 Ollama/Groq provider switch
  ask.py                  Q&A: retrieve -> grounding check -> prompt -> answer
  report.py            on-demand literature review synthesis
  acquire.py            topic -> arXiv search -> LLM relevance + folder judgment -> confirm -> download
streamlit_app.py   the UI — your only entry point day-to-day
```

## Setup (on the lab machine)

**1. Organize your papers** (if you haven't already):
```
<!-- papers/
  hsi_classification/
    paper1.pdf
    paper2.pdf
  hsi_domain_adaptation/
    paper3.pdf
  hsi_generation/
  hsi_vlm/
  hsi_foundation_models/ -->

  topic-1/
    paper1.pdf
    paper2.pdf
  topic-2/
    paper3.pdf
  topic-3/
  topic-4/
  topic-5/

```
Folder names become the subdomain filter in the UI — name them however
you like, there's no fixed taxonomy to configure.

**2. Python environment:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Config:**
```bash
cp .env.example .env
```
Defaults assume `cuda` + `bge-large-en-v1.5`, matching your lab GPU. No
edits needed unless you want to change the model.

**4. Ollama (local LLM):**
```bash
# if not already installed:
curl -fsSL https://ollama.com/install.sh | sh

ollama pull llama3.1:8b
ollama serve   # usually already running as a service — check with:
               # curl http://localhost:11434
```
Your 24GB GPU can run larger models comfortably too — try `llama3.1:70b`
(quantized) or `qwen2.5:32b` if 8B answers feel thin. Just update
`OLLAMA_MODEL` in `.env` and `ollama pull` it first.

**5. Index your papers:**
```bash
python -m app.indexer
```
This downloads the embedding model on first run (a few hundred MB) and
embeds every PDF. Re-run this any time you add, remove, or change PDFs —
it only touches what changed.

**6. Run the app:**
```bash
streamlit run streamlit_app.py
```
Opens in your browser automatically. Ask questions in the chat, filter by
subdomain in the sidebar, and generate a literature review on demand.

## Day-to-day use

- **Add papers:** drop PDFs into the right `papers/<subdomain>/` folder,
  click "Re-index papers" in the sidebar (or run `python -m app.indexer`).
- **Ask anything:** "What datasets are commonly used for domain adaptation
  in HSI?", "What accuracy did [paper] report?", "Is there a method
  similar to [your idea]?" — answers cite the paper + page they came from.
- **Generate a review:** pick a subdomain in the sidebar and click
  "Generate literature review" — this is explicit, not automatic, since
  it costs several LLM calls per run.
- **Find new papers:** type a topic or idea in the sidebar's "Find new
  papers" box and click "Search & judge". It searches arXiv, has the LLM
  judge each candidate's relevance to *that specific topic* (not a fixed
  category rule — this is what makes it precise), and suggests a folder
  per paper (existing or new). Review the checkboxes and folder choices,
  uncheck anything wrong, then click "Download selected". Nothing is
  downloaded until you confirm, and it re-indexes automatically
  afterward. The LLM's judgment won't be perfect — that's expected, it's
  there to narrow candidates for your review, not replace it.

## Known limitations (Phase A — by design)

- No Google Docs export yet — reviews save as local `.md` files. Phase B
  adds a custom MCP server wrapping the Google Docs API, once you've set
  up a Google Cloud OAuth client.
- Chunking is page-based + recursive character splitting, not true
  section detection (no reliable heading markup in most PDFs). Works
  well enough for retrieval; citations are by page, not section name.
- `report.py` approximates a paper's abstract/intro as its first ~2500
  characters of text — works for most papers (front matter comes first),
  but can be noisy for PDFs with unusual layouts (dense title pages,
  multi-column front matter).
- Single collection, local only — this is a personal research tool, not
  built for concurrent multi-user access.

## Troubleshooting

- **"Connection refused" to Ollama:** check `ollama serve` is running and
  `curl http://localhost:11434` responds.
- **Answers feel ungrounded or too vague:** lower `RAG_SIMILARITY_THRESHOLD`
  in `.env` if good matches are being refused, or raise it if irrelevant
  chunks are slipping through. Re-run after editing — no code changes.
- **Indexing is slow on first run:** that's the embedding model loading +
  downloading; later runs are faster since it's cached.
