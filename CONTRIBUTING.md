# Contributing to ews-mcp

Thanks for your interest in this project. Here's how it's organised
and how to engage with it productively.

## Repository layout

```
ewsmcp/                  server package (published as 1.1.1)
tests/                   unit and contract tests
scripts/                 smoke, documentation, and operations utilities
docs/                    usage, API, and architecture documentation
deploy/                  deployment examples
.github/workflows/       tests and image publishing
Dockerfile               container build
pyproject.toml            package metadata and development dependencies
README.md                 product landing page
CHANGELOG.md              version history
```

The server has an in-repository test suite under `tests/`.
It uses mocked Exchange objects and does not require a live mailbox. Its
blocking CI checks run Ruff, the unit and contract tests, a generated API
documentation check, no-Exchange boot smokes, and a Docker build/import
smoke. Tests run on Python 3.11 and 3.12; the boot smokes run on 3.11.

## Filing issues

- **Bug reports**: please include the Exchange auth type (`oauth2` /
  `basic` / `ntlm`), the exchangelib version, the relevant tool name,
  and the verbatim error message + a redacted version of the input
  arguments. **Do not paste real email addresses, internal hostnames,
  or message bodies** — maintainers can investigate using the reported
  shape of the issue without exposing mailbox data.
- **Feature requests**: describe the workflow first, the proposed API
  second. This project aims to keep the MCP doing deterministic
  data work and push reasoning to the consuming agent — see
  [`docs/DESIGN.md`](docs/DESIGN.md) for the design principle.
  Reasoning-shaped tools ("classify this", "summarise that") are unlikely
  to be added because the consuming LLM does them better in-prompt.

## Submitting pull requests

Pull requests are welcome. Before submitting one:

1. **Read the issue / PR for the problem statement and proposed approach**
2. **Reproduce the bug when possible**, without including mailbox data in the PR
3. **Keep the change focused** and follow the conventions described below

All pull requests are reviewed on their merits. The required checks are:
- The PR applies cleanly on top of `main`
- The `tests` workflow passes, including
  tests, boot smokes, API documentation check, and Docker build/import smoke.
- The change must not introduce a new external service dependency
  (e.g. a vector database) without prior discussion in an issue
- Keep the MCP focused on deterministic mailbox operations; see `docs/DESIGN.md`.

## Local development

### Server

```bash
git clone https://github.com/k9fr4n/ews-mcp.git
cd ews-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

python -m pytest -q
python -m ruff check .
python scripts/boot_smoke.py full
python scripts/dump_tool_table.py --check
```

The tests and boot smoke do not need Exchange credentials. For running the
server and configuring its environment, see [`docs/USAGE.md`](docs/USAGE.md).

## Code style

- `ruff check .` and `ruff format --check .` are enforced in CI. Static
  type checking is not currently part of that workflow. Match the
  surrounding style.
- Comments should explain *why*, not *what*.
- Don't add docstrings that just restate the function name.
- Avoid try/except that swallows failures silently — log and re-raise
  with context.
- Don't introduce a new dependency without justifying it in the PR
  description. Pure-stdlib solutions are preferred where practical.

## Security

If you find a vulnerability that affects production deployments
(credential leak, RCE, AuthZ bypass, etc.), **please don't open a
public issue**. Use GitHub's private vulnerability reporting for this
repository, or contact the repository maintainers privately.

## License

By contributing you agree your contribution is licensed under the
project's MIT license.
