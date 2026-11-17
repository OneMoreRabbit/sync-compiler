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

from sync_compiler.compiler import (
    _merge_flags,
    _merge_list,
    compile_plan,
    env_vars,
    resolved_sync_defaults,
)
from sync_compiler.loader import load_main
from sync_compiler.models import DEFAULT_MAX_DELETE, Account, Drive, SyncDefaults

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


class TestOverridesMustBeLists:
    """Found by arch reviewing v0.4.7 (hub #14465).

    A string here is the dangerous shape, not merely the wrong type: the merge
    does list(value), which walks a string letter by letter, and
    `exclude_patterns: "*.log"` then emits `--exclude=*` — excluding
    EVERYTHING, so the sync silently transfers nothing.
    """

    @pytest.mark.parametrize("key", ["exclude_patterns", "sync_flags"])
    def test_a_string_override_is_refused(self, key: str) -> None:
        with pytest.raises(ValidationError, match="must be a list"):
            Drive(id="x", cloud_name="c", local_name="l", enabled=True,
                  overrides={key: "*.log"})

    @pytest.mark.parametrize("key", ["exclude_patterns", "sync_flags"])
    def test_a_proper_list_still_passes(self, key: str) -> None:
        d = Drive(id="x", cloud_name="c", local_name="l", enabled=True,
                  overrides={key: ["*.log"]})
        assert d.overrides[key] == ["*.log"]

    def test_unrelated_override_keys_are_untouched(self) -> None:
        """overrides is free-form; only the two list keys are policed."""
        d = Drive(id="x", cloud_name="c", local_name="l", enabled=True,
                  overrides={"schedule": "*:0/30", "local_subdir": "other"})
        assert d.overrides["schedule"] == "*:0/30"


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


class TestOneWayMaxDelete:
    """0.10: a one-way sync carries the same COUNT bound as a two-way one.

    Operator ruling 2026-11-17. Emitted as MAX_DELETE for the estate wrapper,
    which dry-runs and refuses the run above it. NEVER passed to rclone as
    --max-delete: for a one-way sync that is a count, but it stops part-way
    through a run instead of refusing it, which is the opposite of the point.
    """

    def test_default_is_50(self) -> None:
        assert _defaults().max_delete == DEFAULT_MAX_DELETE == 50

    @pytest.mark.parametrize("bad", [-1, 0])
    def test_unlimited_and_zero_are_refused(self, bad: int) -> None:
        with pytest.raises(ValidationError, match="must be at least 1"):
            _defaults(max_delete=bad)

    def test_emitted_on_every_one_way_instance(self) -> None:
        reg, h = load_main(FIXTURES / "valid" / "arc.yml")
        plan = compile_plan(reg, "arc.yml", h)
        oneway = [i for i in plan.sync_instances
                  if i.mode == "sync" and i.enabled and i.env_vars]
        assert oneway
        for inst in oneway:
            assert inst.env_vars["MAX_DELETE"] == "50"

    def test_never_reaches_rclone_as_a_flag(self) -> None:
        """The count must not become --max-delete on a one-way sync."""
        reg, h = load_main(FIXTURES / "valid" / "arc.yml")
        reg.accounts[0].sync_defaults.max_delete = 7
        plan = compile_plan(reg, "arc.yml", h)
        inst = next(i for i in plan.sync_instances
                    if i.mode == "sync" and i.enabled and i.env_vars)
        assert inst.env_vars["MAX_DELETE"] == "7"
        assert "--max-delete" not in inst.env_vars["SYNC_FLAGS"]

    def test_a_drive_override_wins(self) -> None:
        r = resolved_sync_defaults(_defaults(max_delete=50), {"max_delete": 5}, [])
        assert r.max_delete == 5

    @pytest.mark.parametrize("bad", [0, -1])
    def test_a_drive_override_below_1_fails_and_names_the_drive(self, bad: int) -> None:
        """Asked for by arch (hub #14621) before the tag.

        The shared check reports the field it is given, so an override caught
        inside resolved_sync_defaults said `sync_defaults.max_delete` — sending
        a reader to the account's defaults when the bad value is on one drive.
        Caught on Drive instead, where the name is in hand.
        """
        with pytest.raises(ValidationError) as exc:
            Drive(id="i", cloud_name="c", local_name="academy", enabled=True,
                  overrides={"max_delete": bad})
        message = str(exc.value)
        assert "academy" in message
        assert "overrides.max_delete" in message
        assert "sync_defaults.max_delete" not in message

    def test_a_non_integer_drive_override_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must be an integer"):
            Drive(id="i", cloud_name="c", local_name="academy", enabled=True,
                  overrides={"max_delete": "50"})


class TestUserlessOrgIsNotWarned:
    """0.10: no 'unprovisioned remote' warning when nothing declares one.

    An org whose rclone_users entries all omit remote_name is the deliberately
    userless shape — a personal org reaching its Drive by oauth. Warning that
    its account is unprovisioned says nothing true (arch, hub #14607).
    """

    def _result(self, users, account_remote="drive"):
        from sync_compiler.models import RegistryMain
        from sync_compiler.registry import _validate_rclone_users

        class R:
            def __init__(self):
                self.warnings = []
                self.errors = []
            def warn(self, m, **kw):
                self.warnings.append(m)
            def error(self, m, **kw):
                self.errors.append(m)

        main = RegistryMain.model_validate({
            "meta": {"version": "0.4"},
            "org": "arc",
            "rclone_users": users,
            "platform": {"rclone_user": "rclone_arc", "local_base": "/mnt/raid/arc",
                         "rclone_config": "/var/lib/rclone/rclone.conf"},
            "accounts": [{
                "remote_name": account_remote, "provider": "drive",
                "auth": {"type": "service_account",
                         "service_account_file": "/etc/rclone-sa/x.json"},
                "sync_defaults": {"local_subdir": "drive", "schedule": "*:0/15"},
                "drives": [],
            }],
        })
        r = R()
        _validate_rclone_users(main, Path("arc.yml"), r)
        return r

    def test_userless_org_gets_no_warning(self) -> None:
        r = self._result([{"user": "rclone_arc"}])
        assert not [w for w in r.warnings if "no matching remote_name" in w]

    def test_an_unmatched_account_still_warns(self) -> None:
        """The case the warning exists for keeps working."""
        r = self._result([{"user": "rclone_arc", "remote_name": "other",
                           "provider": "drive"}])
        assert [w for w in r.warnings if "no matching remote_name" in w]
