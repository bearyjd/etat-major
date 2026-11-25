"""One definition of how Git is run safely against a repository we do not trust.

A hostile repository config can name programs (`core.fsmonitor`, `core.hooksPath`, pagers, external
diff drivers). Every Git call in `src/` takes its environment and per-call settings from here.
"""

import os

# Config keys that can make Git execute a program, forced off or to /dev/null for every call.
HARDENED_CONFIG: tuple[tuple[str, str], ...] = (
    ("core.fsmonitor", "false"),
    ("core.hooksPath", os.devnull),
    ("core.attributesFile", os.devnull),
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
