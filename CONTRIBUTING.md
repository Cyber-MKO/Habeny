# Contributing

## Development setup

```bash
pip install -r requirements-dev.txt
cd frontend && npm ci
```

Before opening a pull request, run what CI runs (see README → Linting and Testing):

```bash
ruff check .
HABENY_LXC_BACKEND=direct PYTHONPATH=tests/stubs python3 -m pytest tests/ --cov=app
cd frontend && npm run lint && npm test && npm run build
```

## Pull requests and commits

- Work on a branch and open a pull request against `main`. `main` is only changed through
  pull requests, and CI must be green before merging.
- Keep a pull request to one topic. Split unrelated changes, even small ones.
- Commit messages: a short summary line in the imperative mood, capitalized, with no
  trailing period and at most about 72 characters, e.g.
  `Fix reloading pages whose path is also an API path`. An area prefix is welcome when it
  helps (`Security: …`, `Packaging: …`). Then a blank line and a body that explains why,
  when that isn't obvious from the change.
- Avoid messages that say nothing (`update`, `fix`, `wip`). Squash fix-ups before the pull
  request is merged.
- Add a line under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for anything a user
  or administrator would notice: features, fixes, changed defaults, and upgrade steps.

### About the early history

The commits before September 2026 ("feat: initial source code from lxctest" and similar)
predate these rules. They are left as they are on purpose. Rewriting published history
would change every later commit ID, break existing clones and forks, and orphan the
merged pull requests that refer to them. [CHANGELOG.md](CHANGELOG.md) is the readable
record of what changed.

## Interface text and translations

Wrap text shown in the UI in `t()` from `frontend/src/i18n`: `t("Delete group")`, or with
values `t("{n} containers", { n })`. Write whole sentences, not fragments joined around
variables, so they can be translated. Add the French translation to
`frontend/src/i18n/fr.json`; `npm test` fails when one is missing or a placeholder differs.
New pages should pass an axe-core check (see [docs/accessibility.md](docs/accessibility.md)):
labelled controls, `<h1>` page title, dialogs through `Modal`/`useConfirm`.

## Versions and releases

Habeny uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

- **MAJOR**: an upgrade needs manual steps beyond installing the new version. Examples:
  a removed or renamed setting, API endpoint or CLI command; a database migration that
  can't be undone; dropping a supported OS or Python version.
- **MINOR**: new features, and compatible changes to the API or settings.
- **PATCH**: fixes only.

The version is set in one place, `app/version.py`. The API, the UI, the CLI, backups and
the packages all read it from there.

To release:

1. In a pull request, bump `app/version.py`. In `CHANGELOG.md`, rename `## [Unreleased]`
   to `## [X.Y.Z] - YYYY-MM-DD`, add a new empty `## [Unreleased]` above it, and update the
   links at the bottom. A test checks that the version has a changelog section.
2. After it's merged, go to **Actions → Release → Run workflow** on `main`. You can also push
   a `vX.Y.Z` tag that matches `app/version.py`. The workflow runs the tests, builds the
   tarball, the `.deb` and the offline wheels, tags the commit, and publishes a GitHub release. Its
   notes come from that version's changelog section.

Tick **dry run** to build the artifacts without publishing.
