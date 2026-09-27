# Contributing to ews-mcp

Thanks for your interest in this project. Here's how it's organised
and how to engage with it productively.

## Repository layout

```
v5/                      the 4.5 server (current line)
src/                     legacy 4.0 source (ships as :latest)
docs/                    documentation map; docs/legacy/ = 4.0 docs
.github/workflows/       v5-tests.yml, v5-publish.yml, docker-build-test.yml,
                         docker-publish.yml
Dockerfile               container build
docker-compose.yml       reference docker-compose for local dev
requirements.txt         runtime Python deps for legacy 4.0
setup.py                 distribution metadata for legacy 4.0
v5/pyproject.toml        package metadata and dev dependencies for 4.5
README.md                product landing page
CHANGELOG.md             version history
```

The active 4.5 line has an in-repository test suite under `v5/tests/`.
It uses mocked Exchange objects and does not require a live mailbox. Its
blocking CI checks run Ruff, the unit and contract tests, a generated API
documentation check, no-Exchange boot smokes, and a Docker build/import
smoke. Tests run on Python 3.11 and 3.12; the boot smokes run on 3.11.

The legacy 4.0 line under `src/` has no in-repository test suite. Its CI
builds the legacy Docker image and checks that the Python package imports.
Do not use this legacy CI description for changes under `v5/`.

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
  [`v5/DESIGN.md`](v5/DESIGN.md) for the 4.5 design principle.
  Reasoning-shaped tools ("classify this", "summarise that") are unlikely
  to be added because the consuming LLM does them better in-prompt.

## Submitting pull requests

Pull requests are welcome. Before submitting one:

1. **Read the issue / PR for the problem statement and proposed approach**
2. **Reproduce the bug when possible**, without including mailbox data in the PR
3. **Keep the change focused** and follow the conventions described below

All pull requests are reviewed on their merits. The required checks are:
- The PR applies cleanly on top of `main`
- For changes under `v5/`, the `v5-tests` workflow passes, including
  tests, boot smokes, API documentation check, and Docker build/import smoke.
- For changes to the legacy 4.0 line, the Docker build/import check
  (`docker-build-test.yml`) must pass.
- The change must not introduce a new external service dependency
  (e.g. a vector database) without prior discussion in an issue
- The change must not re-add LLM-reasoning tools removed in v4.0
  (see CHANGELOG for the rationale)

## Local development

### Current line: 4.5 (`v5/`)

```bash
git clone https://github.com/k9fr4n/ews-mcp.git
cd ews-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e './v5[dev]'

python -m pytest v5/tests -q
python -m ruff check v5
python v5/scripts/boot_smoke.py full
python v5/scripts/dump_tool_table.py --check
```

The tests and boot smoke do not need Exchange credentials. For running the
server and configuring its environment, see [`v5/README.md`](v5/README.md).

### Legacy line: 4.0 (`src/`)

```bash
git clone https://github.com/k9fr4n/ews-mcp.git
cd ews-mcp
pip install -r requirements.txt
cp .env.example .env
python -m src.main
```

Or via Docker:

```bash
docker build -t ews-mcp:dev .
docker run -i --rm --env-file .env ews-mcp:dev
```

## Code style

- For 4.5, `ruff check v5` is enforced in CI. Formatting checks and static
  type checking are not currently part of that workflow. Match the
  surrounding style.
- The legacy 4.0 line has no enforced formatter or linter; match the
  surrounding style there as well.
- Comments should explain *why*, not *what*.
- Don't add docstrings that just restate the function name.
- Avoid try/except that swallows failures silently — log and re-raise
  with context.
- Don't introduce a new dependency without justifying it in the PR
  description. Pure-stdlib solutions are preferred for everything
  except the document-extraction libraries already in `requirements.txt`.

## Security

If you find a vulnerability that affects production deployments
(credential leak, RCE, AuthZ bypass, etc.), **please don't open a
public issue**. Use GitHub's private vulnerability reporting for this
repository, or contact the repository maintainers privately.

## License

By contributing you agree your contribution is licensed under the
project's MIT license.
