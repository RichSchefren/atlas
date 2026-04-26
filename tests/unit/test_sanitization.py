"""Unit tests for the pre-LLM sanitization pipeline.

Verifies each component strip + the composed pipeline + the
SanitizationStats reduction-ratio metric Atlas uses to monitor
token-saving effectiveness on real streams.
"""

import pytest


class TestStripAtlasContext:
    def test_removes_simple_block(self):
        from atlas_core.trust.sanitization import strip_atlas_context

        content = "Before <atlas-context>secret data</atlas-context> After"
        out = strip_atlas_context(content)
        assert "secret data" not in out
        assert "Before" in out and "After" in out

    def test_removes_multiline_block(self):
        from atlas_core.trust.sanitization import strip_atlas_context

        content = "<atlas-context>\nline1\nline2\nline3\n</atlas-context>End"
        out = strip_atlas_context(content)
        assert "line1" not in out
        assert "End" in out

    def test_removes_multiple_blocks(self):
        from atlas_core.trust.sanitization import strip_atlas_context

        content = (
            "<atlas-context>a</atlas-context> mid "
            "<atlas-context>b</atlas-context> end"
        )
        out = strip_atlas_context(content)
        assert "<atlas-context>" not in out


class TestStripGraphitiContext:
    def test_removes_block(self):
        from atlas_core.trust.sanitization import strip_graphiti_context

        content = "<graphiti-context>data</graphiti-context>END"
        assert "END" in strip_graphiti_context(content)
        assert "data" not in strip_graphiti_context(content)


class TestStripUntrustedMetadata:
    def test_strips_conversation_info(self):
        from atlas_core.trust.sanitization import strip_untrusted_metadata

        content = (
            "Real content.\n"
            "Conversation info:\n"
            "```json\n"
            "{\"key\": \"value\"}\n"
            "```\n"
            "More real content."
        )
        out = strip_untrusted_metadata(content)
        assert "Real content" in out
        assert "More real content" in out
        assert '"key"' not in out
        assert "Conversation info:" not in out

    def test_strips_sender_metadata(self):
        from atlas_core.trust.sanitization import strip_untrusted_metadata

        content = (
            "Sender (untrusted metadata):\n```json\n{\"sender\":\"x\"}\n```\nbody"
        )
        out = strip_untrusted_metadata(content)
        assert "body" in out
        assert "sender" not in out


class TestStripToolResultWrappers:
    def test_strips_tool_result(self):
        from atlas_core.trust.sanitization import strip_tool_result_wrappers

        content = "Before <tool_result>verbose junk</tool_result> after"
        out = strip_tool_result_wrappers(content)
        assert "verbose junk" not in out
        assert "Before" in out and "after" in out

    def test_strips_function_results(self):
        from atlas_core.trust.sanitization import strip_tool_result_wrappers

        content = "<function_results>foo bar baz</function_results>END"
        out = strip_tool_result_wrappers(content)
        assert "foo bar baz" not in out


class TestNormalizePunctuation:
    def test_replaces_arrows(self):
        from atlas_core.trust.sanitization import normalize_punctuation

        out = normalize_punctuation("A → B ← C ↑ D ↓ E")
        assert out == "A -> B <- C ^ D v E"

    def test_replaces_dashes_and_bullets(self):
        from atlas_core.trust.sanitization import normalize_punctuation

        out = normalize_punctuation("• item — em-dash – en-dash")
        assert "•" not in out
        assert "—" not in out
        assert "–" not in out

    def test_replaces_smart_quotes(self):
        from atlas_core.trust.sanitization import normalize_punctuation

        out = normalize_punctuation("He said “hi” and ‘bye’")
        assert out == 'He said "hi" and \'bye\''


class TestDropUuidOnlyLines:
    def test_removes_uuid_line(self):
        from atlas_core.trust.sanitization import drop_uuid_only_lines

        content = "real line\n12345678-1234-1234-1234-123456789abc\nmore real"
        out = drop_uuid_only_lines(content)
        assert "real line" in out
        assert "more real" in out
        assert "12345678" not in out

    def test_preserves_uuid_in_text(self):
        """UUIDs embedded in sentences must stay."""
        from atlas_core.trust.sanitization import drop_uuid_only_lines

        content = "The id 12345678-1234-1234-1234-123456789abc was assigned."
        out = drop_uuid_only_lines(content)
        assert "12345678" in out


class TestCollapseWhitespace:
    def test_collapses_excess_newlines(self):
        from atlas_core.trust.sanitization import collapse_whitespace

        content = "para1\n\n\n\n\npara2"
        out = collapse_whitespace(content)
        assert out == "para1\n\npara2"

    def test_strips_trailing_whitespace(self):
        from atlas_core.trust.sanitization import collapse_whitespace

        content = "line1   \nline2\t\n"
        out = collapse_whitespace(content)
        assert "line1\nline2" == out


class TestSanitizeForLLM:
    def test_pipeline_composition(self):
        from atlas_core.trust.sanitization import sanitize_for_llm

        content = (
            "<atlas-context>injected</atlas-context>\n"
            "Real claim → important.\n"
            "Conversation info:\n"
            "```json\n"
            "{\"untrusted\": true}\n"
            "```\n"
            "<tool_result>noise</tool_result>\n"
            "12345678-1234-1234-1234-123456789abc\n\n\n\n"
            "End line"
        )
        out = sanitize_for_llm(content)
        assert "injected" not in out
        assert "untrusted" not in out
        assert "noise" not in out
        assert "12345678" not in out
        assert "Real claim -> important." in out  # arrow normalized
        assert "End line" in out
        # No 3+ consecutive newlines remain
        assert "\n\n\n" not in out

    def test_returns_stats_when_requested(self):
        from atlas_core.trust.sanitization import (
            SanitizationStats,
            sanitize_for_llm,
        )

        content = "<atlas-context>X</atlas-context>real text → here"
        result = sanitize_for_llm(content, return_stats=True)
        assert isinstance(result, tuple)
        out, stats = result
        assert isinstance(stats, SanitizationStats)
        assert stats.input_chars == len(content)
        assert stats.output_chars == len(out)
        assert stats.chars_saved > 0
        assert 0.0 < stats.reduction_ratio <= 1.0

    def test_empty_input_handled(self):
        from atlas_core.trust.sanitization import sanitize_for_llm

        assert sanitize_for_llm("") == ""

    def test_clean_input_unchanged_in_substance(self):
        from atlas_core.trust.sanitization import sanitize_for_llm

        # No injectable content — pipeline should pass-through almost verbatim
        content = "Rich said pricing is now $1997 per month."
        out = sanitize_for_llm(content)
        assert "Rich said pricing is now $1997 per month." == out

    def test_realistic_token_saving(self):
        """End-to-end on a transcript shape with multiple noise patterns."""
        from atlas_core.trust.sanitization import sanitize_for_llm

        # Simulated transcript with 50% injected noise
        signal = "Ashley confirmed Q3 launch. Decision: ship by Sept 15."
        noise = (
            "<atlas-context>" + ("X" * 100) + "</atlas-context>\n"
            "Conversation info:\n```json\n" + ("Y" * 100) + "\n```\n"
            "12345678-1234-1234-1234-123456789abc\n"
        )
        content = noise + "\n" + signal
        out, stats = sanitize_for_llm(content, return_stats=True)
        assert signal in out
        # Should achieve substantial reduction
        assert stats.reduction_ratio > 0.4, (
            f"Expected ≥40% reduction; got {stats.reduction_ratio:.2%}"
        )
