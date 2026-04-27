"""Pre-built standard blocks Rich gets out of the box.

Three defaults that get pinned into every WorkingMemoryManager:

  Human       — who Rich is (populated from his Person kref)
  Persona     — Atlas's role description
  CurrentPriorities — auto-populated from open Commitments

Spec: PHASE-5-AND-BEYOND.md § 4.1
"""

from __future__ import annotations

from atlas_core.working.blocks import MemoryBlock

DEFAULT_HUMAN_KREF: str = (
    "kref://AtlasCoffee/People/rich_schefren.person"
)


def build_human_block(human_facts: str | None = None) -> MemoryBlock:
    """Default Human block.

    `human_facts` is the user-provided string. If None, ships with
    a neutral placeholder the user edits via Obsidian (or any text
    editor) before first use.
    """
    content = human_facts or (
        "(unconfigured — replace this with a one-paragraph "
        "self-description that you want Atlas to remember in every "
        "conversation: who you are, what you work on, the names of "
        "the people / projects / programs you reference often.)\n"
        "\n"
        "Edit this block at ~/.atlas/blocks/Human.md or pass "
        "human_facts= when constructing the WorkingMemoryManager."
    )
    return MemoryBlock(
        name="Human",
        content=content,
        write_policy="human",
    )


def build_persona_block(persona: str | None = None) -> MemoryBlock:
    """Default Persona block — describes Atlas's role.

    Override for agent-runtime adapters that want a domain-specific
    persona ("you are an ops agent", "you are a research agent").
    """
    content = persona or (
        "You are Atlas — an open-source local-first cognitive memory "
        "layer with AGM-compliant belief revision.\n"
        "You hold long-term factual beliefs about Rich's work, surface "
        "contradictions when facts change, and route strategic conflicts "
        "to Rich's Obsidian adjudication queue.\n"
        "When asked about Rich's data, prefer to cite the typed graph "
        "with kref:// references rather than paraphrasing."
    )
    return MemoryBlock(
        name="Persona",
        content=content,
        write_policy="auto",
    )


def standard_block_set(
    *,
    human_facts: str | None = None,
    persona: str | None = None,
) -> list[MemoryBlock]:
    """Returns the three default blocks. CurrentPriorities is empty
    by default — the manager populates it via refresh_current_priorities()
    when a Neo4j driver is available."""
    return [
        build_human_block(human_facts),
        build_persona_block(persona),
        MemoryBlock(
            name="CurrentPriorities",
            content="(no priorities loaded — call manager.refresh_current_priorities())",
            write_policy="auto",
        ),
    ]
