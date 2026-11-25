"""Guard the proposed Understand export contract against the claims reviewers found wrong."""

from pathlib import Path

DOC = (Path(__file__).resolve().parents[1] / "docs/contracts/understand-export.md").read_text()


def test_hostname_claim_is_not_overstated() -> None:
    assert "bare hostnames" in DOC
    assert "hostnames, and Git remotes" not in DOC


def test_every_third_party_string_is_sanitized() -> None:
    item7 = DOC.split("7. Anything unsanitized")[1].split("Treat decoded")[0]
    for name in ("`kind`", "`languages`", "`module_scopes`", "`unknown_kinds`", "keys"):
        assert name in item7
    assert "`unknown`" in DOC


def test_names_the_real_sanitizers() -> None:
    assert "planning_text" in DOC
    assert "planning_path" in DOC
    assert "cannot be sanitized" not in DOC
    assert "2,000 characters" not in DOC


def test_flags_are_listed_and_narrow() -> None:
    for flag in ("--source-revision", "--floorplan-revision", "--trail-revision"):
        assert flag in DOC
    assert "does not accept `--repo`" in DOC
    assert "same recorded-input flags as" not in DOC


def test_component_keys_match_planning() -> None:
    assert "`summary_provenance`" in DOC
    assert "`proposed`" in DOC and "`declared`" in DOC


def test_owner_and_reviewer_share_one_privacy_rule() -> None:
    assert "`owner`" in DOC.split("| Q4 |")[1].split("\n")[0]


def test_symbol_counts_define_attribution() -> None:
    assert "source symbol" in DOC
    assert "derived" in DOC


def test_kotlin_note_is_backed_by_the_proof_doc() -> None:
    assert "name-matched and inferred" not in DOC
    assert "weak on the measured sample" in DOC
