# État-major

A self-hosted command center for coding agents running in tmux. It gives one person, or a small family, a strategic view (initiative > project > task) over a fleet of agents, and composes existing tools instead of rebuilding them.

**Status:** pre-implementation. The design is in [docs/SPEC.md](docs/SPEC.md); the evidence behind the component choices is in [docs/RESEARCH.md](docs/RESEARCH.md).

## North stars

1. **Coding on the go:** a phone-friendly web interface to tmux, with audio input and output as an option.
2. **Strategic view per project:** each project's progress overlaid on a roadmap, derived from evidence (merged PRs, tests, releases), not agent self-estimates.
3. **Unattended workflows:** overnight runs that tie into the meute runner, with progress tracked on the board.
4. **Multi-user (roadmap):** a second person under their own login and their own subscription.

## Principles

- Drive the real `claude` and `codex` CLIs in tmux under each user's own login. No subscription proxying, pooling or account switching.
- Git holds intent (markdown tasks); a local store holds runtime state.
- Safe by default: dry-run, human approval for merges and pushes, no push credentials in containers.

## Working in this repo

Read [CLAUDE.md](CLAUDE.md) first. Contributions should keep to the principles above and keep personal paths, hostnames and keys out of the repo.

## License

[AGPL-3.0](LICENSE).
