"""Guard the proposed Understand export contract against the claims reviewers found wrong."""

from pathlib import Path

DOC = (Path(__file__).resolve().parents[1] / "docs/contracts/understand-export.md").read_text()
DOC = " ".join(DOC.split())


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


def test_narrow_loader_keeps_planning_safeguards() -> None:
    assert "same project identifier rule as `load_planning_view`" in DOC
    assert "no records for the configured project" in DOC
    assert "`public_issue`" in DOC


def test_issue_rows_are_sanitized_like_public_issue() -> None:
    assert "`blocking`" in DOC
    assert "80 characters" in DOC
    assert "`_issue_path`" in DOC


def test_unmatchable_is_a_subset_of_unowned_and_counts_are_integers() -> None:
    assert "`unmatchable` is a subset of `unowned`" in DOC
    assert "percentage_owned" in DOC
    assert "no float" in DOC
    assert "`total`" in DOC


def test_artifact_flags_and_dedup_rules_are_stated() -> None:
    assert "caller-supplied" in DOC
    assert "bind_startup_revisions" in DOC
    assert "first symbol seen" in DOC
    assert "`unmatchable_paths`" in DOC
    assert "across the whole model" in DOC


def test_redaction_gaps_are_listed() -> None:
    assert "bare IP addresses" in DOC
    assert "`localhost:port`" in DOC
    assert "email addresses" in DOC
    assert "become a single placeholder" in DOC
    assert "for example a bare comma" in DOC
    assert "[redacted location] location]" not in DOC
