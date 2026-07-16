"""Cross-platform regression tests for SQLite handle lifecycle."""

from pathlib import Path
from tempfile import TemporaryDirectory


def test_store_handles_are_released_before_tempdir_cleanup() -> None:
    from atlas_core.trust import HashChainedLedger, QuarantineStore

    with TemporaryDirectory() as temp:
        root = Path(temp)
        quarantine = QuarantineStore(root / "candidates.db")
        ledger = HashChainedLedger(root / "ledger.db")

        assert quarantine.list_pending() == []
        assert ledger.verify_chain().intact is True

    # Windows raises PermissionError at context exit if either connection is
    # still open. Reaching this assertion is the regression contract.
    assert not root.exists()
