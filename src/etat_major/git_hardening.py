"""One definition of how Git is run safely against a repository we do not trust.

A hostile repository config can name programs (`core.fsmonitor`, `core.hooksPath`, pagers, external
diff drivers, signature verifiers). Git runs in `src/` take their settings from here, which switch
off the programs configured under the fixed keys listed below. The in-process readers also take
their environment from `git_environment()`; the tool runners build their own and add
`config_environment()`.

That is not complete protection. A repository chooses the names of its own `filter.<name>.*`,
`diff.<name>.textconv` and `diff.<name>.command` drivers, so no fixed `-c` list can disable them.
Each runner must also keep to one of these rules:

- A runner that reads the repository's own config (`renames`, `evidence_git`) uses `--bare`, runs
  no command that applies a filter, and passes `--no-ext-diff --no-textconv` to any diff.
- A runner whose external tool runs Git itself (`trail_runner`, `floorplan_runner`) points
  `GIT_DIR` at a private scratch directory, so the repository's config is never loaded.
"""

import os

# Config keys that can make Git execute a program, forced off or to /dev/null for every call.
HARDENED_CONFIG: tuple[tuple[str, str], ...] = (
    ("core.fsmonitor", "false"),
    ("core.hooksPath", os.devnull),
    ("core.attributesFile", os.devnull),
    ("log.showSignature", "false"),
    ("diff.external", ""),
    ("gpg.program", "false"),
    ("gpg.ssh.program", "false"),
    ("gpg.x509.program", "false"),
    ("protocol.allow", "never"),
    ("core.sshCommand", "false"),
    ("core.askPass", "false"),
    ("core.alternateRefsCommand", ""),
)

GIT_CONFIG_ARGS: tuple[str, ...] = (
    "--no-pager",
    *(part for key, value in HARDENED_CONFIG for part in ("-c", f"{key}={value}")),
)


def git_environment() -> dict[str, str]:
    """Return a scrubbed environment: no inherited Git settings, no prompts, no optional locks."""
    return {
        "PATH": os.defpath,
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_ATTR_NOSYSTEM": "1",
    }


def config_environment() -> dict[str, str]:
    """Return the hardened settings as GIT_CONFIG_* variables for tools that run Git themselves."""
    env = {"GIT_CONFIG_COUNT": str(len(HARDENED_CONFIG))}
    for index, (key, value) in enumerate(HARDENED_CONFIG):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env
