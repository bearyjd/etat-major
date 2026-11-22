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
        ("fp:n:area/component:variant", "fp:n", None, "area/component:variant", None),
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
        "fp:n:/root",
        "fp:n:area\x1b",
        "fp:n:area\u202e",
        "fp:n:area component",
        "fp:f:app/./x.py",
        "fp:f:app/../x.py",
        "fp:f:app\\x.py",
        "fp:f:app/%2e%2e/x.py",
        "fp:f:app/\x00x.py",
        "fp:f:app/\x1bx.py",
        "fp:f:app/\u202ex.py",
        "trail:app/./x.py#symbol",
        "trail:app/x.py#symbol\x1b",
        "trail:app/x.py#symbol\u202e",
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


@pytest.mark.parametrize("prefix,suffix", [("fp:f:", ""), ("trail:", "#symbol")])
@pytest.mark.parametrize(
    "path", ["a//b", "a/b/", "~/x", "~user/x", "C:/x", "c:x", "a∕b", "a／b", "a⁄b", "a⧸b"]
)
def test_code_ref_rejects_ambiguous_paths(prefix, suffix, path):
    with pytest.raises(RefError, match="path must be relative"):
        parse_ref(prefix + path + suffix)


@pytest.mark.parametrize("prefix,suffix", [("fp:f:", ""), ("trail:", "#symbol")])
@pytest.mark.parametrize("path", ["main.py", "src/sub/main.py", "café/entrée.py", "src/~draft.py"])
def test_code_ref_accepts_relative_paths(prefix, suffix, path):
    assert str(parse_ref(prefix + path + suffix)) == prefix + path + suffix


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


def test_ref_error_bounds_unknown_kind_and_input():
    value = "x" * 100 + "\x1b[31m:unused"
    with pytest.raises(RefError) as exc:
        parse_ref(value)
    message = str(exc.value)
    assert exc.value.text == value
    assert "x" * 80 in message
    assert "x" * 81 not in message
    assert "\x1b" not in message


def test_non_string_ref_diagnostic_does_not_render_container_contents():
    with pytest.raises(RefError, match="reference must be a string") as exc:
        parse_ref([["invalid reference content"]])  # type: ignore[arg-type]
    assert "<list>" in str(exc.value)
    assert "invalid reference content" not in str(exc.value)
