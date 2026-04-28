# Show HN — First-comment Q&A primer

Paste this as the **first reply on your own Show HN** at submission time. It primes the predictable HN questions and sets the tone for the thread.

---

> (OP) Couple of notes for HN that I'd want to know if I were reading this cold:
>
> **Why a new memory system?** The premise is narrow: when a fact in your memory changes, what happens to every belief that depended on it? Vector retrieval gives you the right document but doesn't tell you whether the document is still right. Atlas's `Ripple` algorithm walks the typed `DEPENDS_ON` graph the moment a fact changes and re-evaluates downstream confidence — automatically. That's the differentiator vs. Mem0, Letta, Memori, Graphiti, Kumiho.
>
> **What's "AGM-compliant"?** The Alchourrón-Gärdenfors-Makinson postulates K\*2–K\*6 plus Hansson Relevance/Core-Retainment. Formal correctness for belief revision (1985 paper, still load-bearing). Atlas runs the same shape of 49-scenario compliance suite as Kumiho and passes 100%. Reproducibility artifact at docs/AGM_COMPLIANCE.md.
>
> **Is this just RAG with extra steps?** No. RAG is retrieval-time reasoning. Atlas adds *ingestion-time* reasoning. The cascade fires when a fact changes, not when a question gets asked. Worked example with the failure mode at docs/WHY_VECTOR_IS_NOT_ENOUGH.md.
>
> **How do I run it?** `git clone … && docker compose up -d && pip install -e .[dev] && ./demo.sh`. ~12 seconds to see the loop close on a synthetic graph; `make demo-messy` runs the same loop on a real markdown note + meeting transcript. No API keys required for the core path. No telemetry. Local-first means a single Neo4j instance + SQLite ledger on your machine.
>
> **What does Atlas NOT do?** It's not a chatbot UI. It's not a Letta replacement (Letta runs agent loops; Atlas slots underneath). It's not a managed cloud service. The "what Atlas does worse" subsection in the README is honest about the tradeoffs.
>
> Happy to answer anything specific. The Cypher's all open, the AGM operators have property-based tests, and the BMB benchmark is checked in with a reproducible seed.
