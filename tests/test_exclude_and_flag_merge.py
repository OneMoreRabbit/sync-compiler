"""v0.4.7 — whitespace in exclude patterns refused; flag repeats kept.

Both faults have the same shape: a value that word-splits at the consumer into
stray POSITIONAL arguments, which on an rclone sync command are the source and
destination. So neither is a missed option — each changes what the command
operates on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sync_compiler.compiler import _merge_flags, _merge_list, env_vars
from sync_compiler.loader import load_main
from sync_compiler.models import Account, Drive, SyncDefaults

FIXTURES = Path(__file__).parent / "fixtures"


def _defaults(**kw):
    base = {"local_subdir": "drive", "schedule": "*:0/15"}
    base.update(kw)
    return SyncDefaults(**base)


class TestWhitespaceInExcludePatternsIsRefused:
    """All three layers that reach EXCLUDE_PATTERNS."""

    @pytest.mark.parametrize("bad", ["Weekly sync Recording", "a\tb", "trailing "])
    def test_layer_1_account_defaults(self, bad: str) -> None:
        with pytest.raises(ValidationError, match="contains whitespace"):
            _defaults(exclude_patterns=[bad])

    def test_layer_2_drive_overrides(self) -> None:
        """The layer a per-drive exclusion is actually written in.

        `overrides` is a free-form dict, so SyncDefaults' validator does not
        cover it even though its exclude_patterns are merged in.
        """
        with pytest.raises(ValidationError, match="contains whitespace"):
            Drive(id="x", cloud_name="c", local_name="l", enabled=True,
                  overrides={"exclude_patterns": ["Weekly sync Recording"]})

    def test_layer_3_additional_excludes(self) -> None:
        with pytest.raises(ValidationError, match="contains whitespace"):
            Account(remote_name="drive", provider="drive", auth={
                        "type": "service_account",
                        "service_account_file": "/etc/rclone-sa/x.json"},
                    sync_defaults=_defaults(),
                    additional_excludes=["Weekly sync Recording"])

    def test_the_question_mark_form_is_allowed(self) -> None:
        """`?` per space is the way until --exclude-from exists."""
        d = _defaults(exclude_patterns=["/Departments/Engineering/Weekly?sync?Recording"])
        assert d.exclude_patterns == ["/Departments/Engineering/Weekly?sync?Recording"]

    def test_ordinary_patterns_still_pass(self) -> None:
        d = _defaults(exclude_patterns=["*.tmp", ".DS_Store", "archive/**"])
        assert len(d.exclude_patterns) == 3

    def test_the_emitted_string_is_space_joined(self, tmp_path: Path) -> None:
        """Why the check exists: nothing marks where one pattern ends."""
        reg, _ = load_main(FIXTURES / "valid" / "arc.yml")
        acct = reg.accounts[0]
        resolved = _defaults(exclude_patterns=["*.tmp", "archive/**"])
        got = env_vars(reg, acct, acct.drives[0], resolved)["EXCLUDE_PATTERNS"]
        assert got == "--exclude=*.tmp --exclude=archive/**"


class TestFlagMerge:
    """arch ruling hub #14440: keep repeats, drop only exact baseline repeats."""

    def test_a_flag_repeated_with_values_keeps_both(self) -> None:
        """The 0.4.6 fault. Deduping left the second value orphaned."""
        assert _merge_flags(["--no-update-dir-modtime"],
                            ["--max-age", "7d", "--max-age", "30d"]) == [
            "--no-update-dir-modtime", "--max-age", "7d", "--max-age", "30d"]

    def test_an_exact_baseline_repeat_is_removed(self) -> None:
        assert _merge_flags(["--no-update-dir-modtime"],
                            ["--no-update-dir-modtime", "--fast-list"]) == [
            "--no-update-dir-modtime", "--fast-list"]

    def test_baseline_comes_first(self) -> None:
        assert _merge_flags(["--base"], ["--other"])[0] == "--base"

    def test_merge_list_still_dedupes_for_patterns(self) -> None:
        """Patterns keep the union merge: a repeated pattern is a no-op."""
        assert _merge_list(["*.tmp"], ["*.tmp", "archive/**"]) == ["*.tmp", "archive/**"]
