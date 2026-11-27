import random

import pytest

from etat_major.planning_issues import planning_text
from etat_major.text_safety import _PRIVATE_LOCATION, _SCP_REMOTE, public_text

R = "[redacted location]"

# Every token spelled S<n>x is secret and must not survive redaction.
CORPUS = [
    ("host build-box.lan:/srv/S1x", f"host {R}"),
    ("https://u:S1x@h.invalid/S2x?t=S3x", R),
    ("ssh://git@h.invalid:22/S1x", R),
    ("file:///srv/S1x", R),
    ("git@h.invalid:org/S1x.git", R),
    ("deploy@box:S1x", R),
    ("deploy@h.invalid:/srv/S1x", R),
    ("h.invalid:S1x", R),
    ("h.invalid:srv/S1x", R),
    ("h.invalid:/srv/S1x", R),
    ("h.invalid:~/S1x", R),
    ("h.invalid:C:\\S1x", R),
    ("h.invalid:\\\\srv\\S1x", R),
    ("h.invalid:https://other.invalid/S1x", R),
    ("box:srv/S1x", R),
    ("box:/srv/S1x", R),
    ("box:S1x.git", R),
    ("[2001:db8::1]:S1x", R),
    ("[2001:db8::1]:/srv/S1x", R),
    ("git@[2001:db8::1]:/srv/S1x", R),
    ("/srv/S1x", R),
    ("~/S1x", R),
    ("C:\\S1x", R),
    ("c:/S1x", R),
    ("\\\\server\\share\\S1x", R),
    ("\\\\?\\C:\\S1x", R),
    ('"h.invalid:/srv/S1x"', f'"{R}"'),
    ("<h.invalid:/srv/S1x>", f"<{R}>"),
    ("(h.invalid:/srv/S1x) /srv/S2x", f"({R} {R}"),
    ("h.invalid:/srv/S1x h.invalid:/srv/S2x", f"{R} {R}"),
    # Adjacent and overlapping spans.
    ("/a/S1x,/b/S2x", R),
    ("/a/S1x,h.invalid:/b/S2x", R),
    # A span contained in an earlier one must not shorten the merged span.
    ("/a/S1x,h.invalid:S2x:S3x", R),
    ("h.invalid:x-/S1x:S2x", R),
    ("h.invalid:x=/srv/S1x", R),
    ("h.invalid:S1x=C:\\S2x", R),
    ("h.invalid:S1x:/srv/S2x", f"{R}:{R}"),
    (f"{R}/srv/S1x", R),
    (f"h.invalid:{R}", R),
]

_MARKERS = [f"S{number}x" for number in range(1, 4)]


def _two_pass(value: str) -> str:
    """The earlier implementation, kept as an oracle for what it used to hide."""
    return _SCP_REMOTE.sub(R, _PRIVATE_LOCATION.sub(R, value))


@pytest.mark.parametrize(("value", "expected"), CORPUS)
def test_each_sensitive_span_is_redacted_once(value, expected):
    assert planning_text(value) == expected


@pytest.mark.parametrize("value", [value for value, _ in CORPUS])
def test_nothing_hidden_by_two_passes_becomes_visible(value):
    old, new = _two_pass(value), public_text(value, scp_remotes=True)
    for marker in _MARKERS:
        assert marker in old or marker not in new


@pytest.mark.parametrize("value", [value for value, _ in CORPUS])
def test_redacting_already_redacted_text_does_not_damage_placeholders(value):
    once = public_text(value)
    twice = planning_text(once)
    assert twice.count("redacted") == twice.count(R)
    assert twice.count("location") == twice.count(R)
    assert planning_text(planning_text(value)) == planning_text(value)


def test_without_scp_remotes_only_the_location_is_redacted():
    assert public_text("host h.invalid:/srv/S1x") == f"host h.invalid:{R}"


_FORMS = [
    "https://u:{0}@h.invalid/{1}",
    "git@h.invalid:org/{0}.git",
    "h.invalid:/srv/{0}",
    "h.invalid:{0}",
    "h.invalid:C:\\{0}",
    "u@h.invalid:~/{0}",
    "box:srv/{0}",
    "box:{0}.git",
    "[2001:db8::1]:{0}",
    "/srv/{0}",
    "~/{0}",
    "C:\\{0}\\{1}",
    "\\\\server\\{0}",
    "h.invalid:x-/{0}:{1}",
]
_SEPARATORS = [" ", "\n", "\t", ", ", "; ", " and ", '" "', "' '", "> <", " ("]


def test_random_mixtures_never_leak_secrets():
    rng = random.Random(20261125)  # noqa: S311
    for case in range(2000):
        secrets, parts = [], []
        for index in range(rng.randint(1, 5)):
            tokens = [f"secret{case}n{index}{side}z" for side in "ab"]
            form = rng.choice(_FORMS)
            secrets += [token for slot, token in enumerate(tokens) if f"{{{slot}}}" in form]
            parts += [form.format(*tokens), rng.choice(_SEPARATORS)]
        value = "".join(parts)
        output = public_text(value, scp_remotes=True)
        assert not [secret for secret in secrets if secret in output], (value, output)
        assert output.count("redacted") == output.count(R), (value, output)
        assert output.count("location") == output.count(R), (value, output)
