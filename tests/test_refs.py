import pytest

from etat_major.refs import Ref, RefError, parse_ref


@pytest.mark.parametrize(
    ("text", "kind", "project", "ident", "fragment"),
    [
        ("feature:netlens/0031", "feature", "netlens", "0031", None),
        ("task:netlens/0042", "task", "netlens", "0042", None),
        ("milestone:netlens/m3", "milestone", "netlens", "m3", None),
        ("research:0007", "research", None, "0007", None),
        ("research:0007#f1", "research", None, "0007", "f1"),
        ("decision:0012", "decision", None, "0012", None),
        ("fp:n:ui.hostdetail", "fp:n", None, "ui.hostdetail", None),
        ("fp:f:app/src/Latency.kt", "fp:f", None, "app/src/Latency.kt", None),
        (
            "trail:app/src/Latency.kt#Latency.sample",
            "trail",
            None,
            "app/src/Latency.kt",
            "Latency.sample",
        ),
    ],
)
def test_valid_refs(text, kind, project, ident, fragment):
    ref = parse_ref(text)
    assert (ref.kind, ref.project, ref.id, ref.fragment) == (kind, project, ident, fragment)
    assert str(ref) == text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "feature:0031",  # project-scoped kind needs a project
        "feature:netlens/",
        "feature:netlens/0031#f1",  # no fragment on features
        "task:netlens",
        "research:netlens/0007",  # research ids are global
        "decision:0012#f1",
        "research:0007#",
        "research:",
        "unknown:1",
        "Feature:netlens/0031",
        "feature netlens/0031",
        "fp:x:foo",
        "fp:n:",
        "fp:f:",
        "fp:f:/abs/path.py",
        "fp:f:../escape.py",
        "fp:n:ui.hostdetail#sym",
        "trail:app/x.py",  # symbol required
        "trail:app/x.py#",
        "trail:#sym",
        "trail:/abs.py#s",
        "feature:netlens/0031 ",
    ],
)
def test_invalid_refs(text):
    with pytest.raises(RefError) as exc:
        parse_ref(text)
    assert repr(text) in str(exc.value) or text == ""


def test_non_string_rejected():
    with pytest.raises(RefError):
        parse_ref(7)  # type: ignore[arg-type]


def test_ref_is_immutable_and_hashable():
    ref = parse_ref("research:0007#f1")
    with pytest.raises(AttributeError):
        ref.id = "x"  # type: ignore[misc]
    assert {ref, parse_ref("research:0007#f1")} == {ref}
    assert isinstance(ref, Ref)


def test_error_names_grammar():
    with pytest.raises(RefError, match="expected"):
        parse_ref("bogus")
