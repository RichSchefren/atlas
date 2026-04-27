"""Unit tests for LLM extractors + token budget.

Spec: PHASE-5-AND-BEYOND.md § 1.4
"""

import json
from unittest.mock import MagicMock

import pytest

# ─── TokenBudget ────────────────────────────────────────────────────────────


class TestTokenBudget:
    def test_fresh_state_is_zero_spend(self, tmp_path):
        from atlas_core.ingestion.budget import TokenBudget
        b = TokenBudget(path=tmp_path / "budget.sqlite", daily_cap_usd=5.0)
        state = b.state()
        assert state.spent_usd == 0.0
        assert state.daily_cap_usd == 5.0
        assert not state.is_exhausted
        assert state.remaining_usd == 5.0

    def test_charge_increments_spend(self, tmp_path):
        from atlas_core.ingestion.budget import TokenBudget
        b = TokenBudget(path=tmp_path / "budget.sqlite", daily_cap_usd=5.0)
        # 1000 in + 200 out at Haiku = 0.001 + 0.001 = 0.002 USD
        state = b.charge(1000, 200)
        assert state.spent_usd > 0
        assert state.remaining_usd < 5.0

    def test_exhaustion_flag(self, tmp_path):
        from atlas_core.ingestion.budget import TokenBudget
        b = TokenBudget(path=tmp_path / "budget.sqlite", daily_cap_usd=0.001)
        state = b.charge(10_000, 10_000)
        assert state.is_exhausted

    def test_can_afford_pre_check(self, tmp_path):
        from atlas_core.ingestion.budget import TokenBudget
        b = TokenBudget(path=tmp_path / "budget.sqlite", daily_cap_usd=5.0)
        assert b.can_afford(1000, 1000) is True
        assert b.can_afford(10_000_000, 10_000_000) is False

    def test_persists_across_instances(self, tmp_path):
        from atlas_core.ingestion.budget import TokenBudget
        path = tmp_path / "budget.sqlite"
        b1 = TokenBudget(path=path, daily_cap_usd=5.0)
        b1.charge(1000, 1000)
        spent_first = b1.state().spent_usd

        b2 = TokenBudget(path=path, daily_cap_usd=5.0)
        assert b2.state().spent_usd == spent_first

    def test_reset_today_clears(self, tmp_path):
        from atlas_core.ingestion.budget import TokenBudget
        b = TokenBudget(path=tmp_path / "budget.sqlite", daily_cap_usd=5.0)
        b.charge(1000, 1000)
        assert b.state().spent_usd > 0
        b.reset_today()
        assert b.state().spent_usd == 0


# ─── LLMExtractor base ──────────────────────────────────────────────────────


class TestLLMExtractorBase:
    def test_load_prompt_template_finds_vault(self):
        from atlas_core.ingestion.extractors import load_prompt_template
        text = load_prompt_template("vault")
        assert "{note_body}" in text

    def test_load_prompt_template_missing_raises(self):
        from atlas_core.ingestion.extractors import load_prompt_template
        with pytest.raises(FileNotFoundError):
            load_prompt_template("does_not_exist")

    def test_parse_jsonl_handles_clean_input(self):
        from atlas_core.ingestion.extractors.llm_base import LLMExtractor
        text = (
            '{"subject":"Sarah","predicate":"is","object_value":"CEO"}\n'
            '{"subject":"Marcus","predicate":"is","object_value":"Roaster"}\n'
        )
        rows = LLMExtractor._parse_jsonl(text)
        assert len(rows) == 2
        assert rows[0]["subject"] == "Sarah"

    def test_parse_jsonl_skips_malformed(self):
        from atlas_core.ingestion.extractors.llm_base import LLMExtractor
        text = (
            '{"subject":"a","predicate":"x","object_value":"y"}\n'
            'this is not json\n'
            '{"subject":"b","predicate":"x","object_value":"y"}\n'
            '\n'
            '# comment line\n'
        )
        rows = LLMExtractor._parse_jsonl(text)
        assert len(rows) == 2
        assert {r["subject"] for r in rows} == {"a", "b"}


# ─── Vault LLM extractor ────────────────────────────────────────────────────


class TestVaultLLMExtractor:
    def test_strips_frontmatter_and_short_circuits(self, tmp_path, monkeypatch):
        from atlas_core.ingestion.budget import TokenBudget
        from atlas_core.ingestion.extractors import VaultLLMExtractor
        budget = TokenBudget(path=tmp_path / "budget.sqlite", daily_cap_usd=5)
        ext = VaultLLMExtractor(budget=budget)

        text = "---\ntitle: Test\n---\n\nShort body."  # < MIN_BODY_CHARS
        result = ext.extract_from_text(text)
        assert result.succeeded is False
        assert "too short" in result.skipped_reason

    def test_budget_exhausted_skips_call(self, tmp_path):
        from atlas_core.ingestion.budget import TokenBudget
        from atlas_core.ingestion.extractors import VaultLLMExtractor
        budget = TokenBudget(path=tmp_path / "budget.sqlite", daily_cap_usd=5.0)
        # Burn the entire budget
        budget.charge(10_000_000, 10_000_000)
        ext = VaultLLMExtractor(budget=budget)
        long_body = "X" * 600  # well past MIN_BODY_CHARS
        result = ext.extract_from_text(long_body)
        assert result.succeeded is False
        assert "budget exhausted" in result.skipped_reason

    def test_successful_call_charges_budget(self, tmp_path):
        from atlas_core.ingestion.budget import TokenBudget
        from atlas_core.ingestion.extractors import VaultLLMExtractor

        budget = TokenBudget(path=tmp_path / "budget.sqlite", daily_cap_usd=5.0)
        ext = VaultLLMExtractor(budget=budget)

        # Mock the Anthropic client to avoid a real network call
        fake_response = MagicMock()
        fake_response.content = [MagicMock(text=(
            '{"subject":"Sarah","predicate":"role","object_value":"CEO",'
            '"confidence":0.9,"assertion_type":"factual_assertion"}\n'
            '{"subject":"Marcus","predicate":"role","object_value":"Roaster",'
            '"confidence":0.85,"assertion_type":"factual_assertion"}\n'
        ))]
        fake_response.usage = MagicMock(input_tokens=500, output_tokens=200)
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_response
        ext._client = fake_client

        # Force template loading — the {note_body} placeholder is
        # replaced via str.replace() (not .format) to tolerate JSON
        # braces in the real prompts.
        ext._template = "TEMPLATE:\n{note_body}"

        long_body = (
            "Sarah is the CEO and Marcus runs the roastery. "
            "We've decided to ship next quarter. "
        ) * 10  # > MIN_BODY_CHARS
        result = ext.extract_from_text(long_body)
        assert result.succeeded is True
        assert len(result.assertions) == 2
        assert result.assertions[0]["subject"] == "Sarah"
        assert result.input_tokens == 500
        assert result.output_tokens == 200
        assert result.cost_usd > 0
        # Budget should reflect the spend
        assert budget.state().spent_usd > 0


# ─── Claude session conversation builder ────────────────────────────────────


class TestClaudeSessionConversationBuilder:
    def test_builds_user_assistant_pairs(self, tmp_path):
        from atlas_core.ingestion.extractors import ClaudeSessionLLMExtractor

        path = tmp_path / "session.jsonl"
        rows = [
            {"type": "file-history-snapshot"},  # skipped
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "Build the auth module",
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": "Sure, here's the plan...",
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "<local-command-caveat>noise",  # skipped
                },
            },
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows))

        text = ClaudeSessionLLMExtractor._build_conversation_text(path)
        assert "USER: Build the auth module" in text
        assert "ASSISTANT: Sure, here's the plan..." in text
        assert "local-command-caveat" not in text
