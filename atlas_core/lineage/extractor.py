"""Decision → SUPPORTS → Belief edge extractor.

When an LLM extractor pulls a Decision from a vault note or
transcript, this module asks the LLM a follow-up question:
"what beliefs did this decision rest on?" The result is a list of
SUPPORTS edges that get materialized in Neo4j.

Each SUPPORTS edge carries:
  - strength (0-1): how strongly the decision depends on the belief
  - source_episode (kref): the episode where the dependency was asserted

Spec: PHASE-5-AND-BEYOND.md § 1.5
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from atlas_core.ingestion.budget import TokenBudget, estimate_haiku_cost


log = logging.getLogger(__name__)


DEFAULT_LLM_MODEL: str = "claude-haiku-4-5-20251001"


SUPPORTS_EXTRACTION_PROMPT: str = """You are extracting the belief
chain underneath a strategic decision Rich Schefren made.

Decision: {decision_text}

Context (the surrounding paragraph or paragraphs that explain WHY):
{context}

Output ONE JSON object per line (JSONL). Each line is a belief that
this decision rests on:
  {"belief_kref": "<kref string OR free-text identifier if no kref yet>",
   "belief_text": "<the belief in one sentence>",
   "strength": <0.0..1.0>,
   "rationale": "<why this belief supports the decision>"}

Rules:
- 1-5 supports per decision. Don't pad.
- strength 0.95 = decision is unrecoverable if belief weakens
- strength 0.7 = decision is partly contingent
- strength 0.4 = belief is corroborating but not load-bearing
- If no clear support exists, output zero lines.

JSONL only, no commentary.
"""


@dataclass
class SupportsEdge:
    """One edge in a decision's belief chain."""

    decision_kref: str
    belief_kref: str
    belief_text: str
    strength: float
    rationale: str


class LineageExtractor:
    """LLM-driven SUPPORTS edge extractor.

    Constructed once, called per-decision. Lazy Anthropic client init,
    budget-gated calls.
    """

    def __init__(
        self,
        *,
        budget: TokenBudget | None = None,
        model: str = DEFAULT_LLM_MODEL,
    ):
        self.budget = budget or TokenBudget()
        self.model = model
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY required for lineage extraction"
            )
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic SDK required") from exc
        self._client = Anthropic(api_key=api_key)

    def extract(
        self,
        decision_kref: str,
        decision_text: str,
        context: str,
    ) -> list[SupportsEdge]:
        """Fire one LLM call to extract SUPPORTS edges.

        Returns [] when budget exhausted or context too thin. Never
        raises on extraction failure — partial recovery beats crash.
        """
        # Budget pre-check
        est_in = max(1, (len(decision_text) + len(context)) // 4 + 200)
        est_out = 600
        if not self.budget.can_afford(est_in, est_out):
            log.info("Lineage extraction skipped: budget exhausted")
            return []

        if not context.strip() or len(context) < 50:
            return []

        prompt = SUPPORTS_EXTRACTION_PROMPT.replace(
            "{decision_text}", decision_text,
        ).replace("{context}", context[:8000])

        self._ensure_client()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=est_out,
            messages=[{"role": "user", "content": prompt}],
        )
        actual_in = response.usage.input_tokens
        actual_out = response.usage.output_tokens
        self.budget.charge(actual_in, actual_out)

        text = response.content[0].text
        edges: list[SupportsEdge] = []
        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            edges.append(SupportsEdge(
                decision_kref=decision_kref,
                belief_kref=str(obj.get("belief_kref", "")),
                belief_text=str(obj.get("belief_text", "")),
                strength=float(obj.get("strength", 0.5)),
                rationale=str(obj.get("rationale", "")),
            ))
        return edges


async def extract_supports_edges(
    driver,
    *,
    decision_kref: str,
    decision_text: str,
    context: str,
    budget: TokenBudget | None = None,
) -> list[SupportsEdge]:
    """Convenience: extract supports + materialize them as SUPPORTS
    edges in Neo4j atomically."""
    extractor = LineageExtractor(budget=budget)
    edges = extractor.extract(decision_kref, decision_text, context)
    if not edges:
        return []

    async with driver.session() as session:
        for edge in edges:
            # Upsert the belief node if it doesn't exist; use the
            # belief_kref directly if structured, else mint one from
            # the belief_text fingerprint.
            target_kref = edge.belief_kref or _kref_from_text(edge.belief_text)
            await session.run(
                "MERGE (b:Belief:AtlasItem {kref: $bk}) "
                "ON CREATE SET b.text = $bt, b.confidence_score = 0.7, "
                "              b.deprecated = false "
                "WITH b "
                "MERGE (d:Decision:AtlasItem {kref: $dk}) "
                "MERGE (d)-[r:SUPPORTS {strength: $strength}]->(b) "
                "ON CREATE SET r.rationale = $rationale",
                bk=target_kref, bt=edge.belief_text,
                dk=edge.decision_kref,
                strength=edge.strength,
                rationale=edge.rationale,
            )
    return edges


def _kref_from_text(belief_text: str) -> str:
    """Synthesize a kref for a free-text belief that doesn't yet
    have a canonical form. Hash-based so the same text always maps
    to the same kref."""
    import hashlib
    digest = hashlib.sha256(belief_text.encode("utf-8")).hexdigest()[:12]
    return f"kref://Atlas/Beliefs/auto_{digest}.belief"
