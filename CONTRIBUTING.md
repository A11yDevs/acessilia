# Contributing to Acessilia

Thanks for considering a contribution! This document defines the project's guidelines based on a **simplified Git Flow**, designed to keep the agility typical of open-source projects.

You can also read these guidelines in **Brazilian Portuguese**: [português brasileiro](CONTRIBUTING.pt-br.md)

## Branching model

```
main  ──────────────●──────────────────●──  (stable releases)
   \              /  \                /
    develop ─────●─── release/x.y.z ─●────  (integration)
        \        /  \       |       /
         feat/* ──   fix/* ─┴──────
```

### Eternal branches

| Branch | Purpose |
|--------|---------|
| `main` | **Production.** Stable, reviewed code. Merges in only from `develop` or `hotfix/*`. |
| `develop` | **Integration.** Where work-in-progress features meet. The default collaboration branch. |

### Roles and permissions

| Role | Who | Permissions |
|------|-----|-------------|
| **Maintainers** | [@marceloakira](https://github.com/marceloakira), [@jhonata192](https://github.com/jhonata192), and [@fragaeduardo](https://github.com/fragaeduardo) | The only people authorized to merge `develop → main` and create releases. |
| **Collaborators** | Everyone else | May open PRs against `develop` and review them. |

> **Important:** temporary branches must be deleted after their merge.

### Temporary branches

| Prefix | Purpose | Born from | Merges into |
|--------|---------|-----------|-------------|
| `feat/*` | New feature | `develop` | `develop` |
| `fix/*` | Bug fix | `develop` | `develop` (or `release/*` during BHS, see [section 5.1](#51-bug-huntingsquashing-bhs)) |
| `docs/*` | Documentation | `develop` | `develop` |
| `refactor/*` | Refactoring | `develop` | `develop` |
| `chore/*` | Maintenance (deps, CI, config) | `develop` | `develop` |
| `release/*` | Stabilisation of a release (BHS cycle) | `develop` | `main` e `develop` |
| `hotfix/*` | Critical production fix | `main` | `main` and `develop` |

> **Important:** temporary branches must be deleted after their merge.

## Running locally with Docker

For detailed instructions on bringing up Acessilia with Docker — both from a local build and from the pre-published GHCR images (without needing the source tree) — see the dedicated guide:

📄 [`docs/docker-compose.md`](docs/docker-compose.md)

## Daily workflow

### 1. Starting a task

```bash
# Sync with develop
git checkout develop
git pull

# Create a branch for the task
git checkout -b feat/my-feature
```

### 2. Developing

Before changing responsibilities or dependencies between the core, the SDK,
docstruct and the Toolbox, check the
[constitution](docs/constitution.md#7-ecosystem-architecture-principles) and the
[Architecture Decision Records](docs/adr/README.md). Such a change, a new public
contract, or an exception to a principle needs an ADR.

Make atomic commits following the [commit convention](#commit-convention).

```bash
git add .
git commit -m "feat(api): adds EPUB export endpoint"
```

### 3. Staying in sync

Always rebase against `develop` to avoid large conflict resolutions:

```bash
git fetch origin
git rebase origin/develop
```

### 4. Sending it for review

Before opening the Pull Request, make sure all tests pass:

```bash
uv run pytest tests/ -v
```

The CI pipeline runs the test suite automatically on GitHub; a PR can only be reviewed once **all tests are green**.

```bash
# Option A — via GitHub (recommended)
git push origin feat/my-feature
# Open a Pull Request from feat/my-feature → develop

# Option B — local merge (for simple changes)
git checkout develop
git merge feat/my-feature
git push origin develop
git branch -d feat/my-feature
```

### 5. Staging (QA)

After a PR merges into `develop`, the **CD pipeline** (`.github/workflows/delivery.yml`) automatically builds a Docker image and publishes it to GHCR with tags `develop` and `sha-<commit>`.

The staging server runs from a clone of this repository and a systemd user timer
(`acessilia-staging-update.timer`) that checks the tracked branch every 5 minutes and
updates the container once the image of a new commit is on GHCR. `scripts/ops.sh` installs
and operates it; see [docs/homologacao-systemd.md](docs/homologacao-systemd.md).

- `docker-compose.staging.yml` — defines the container
- `scripts/ops.sh` — `auto-update setup|status|start|migrate`, `track` and the BHS commands
- `scripts/staging-update.sh` — the update itself, run by `ops.sh auto-update start`

```bash
# Check which image is live (via the health API)
curl http://homologacao:8000/api/v1/health | jq .

# Or, on the server, the full picture
./scripts/ops.sh auto-update status
```

### 5.1 Bug Hunting/Squashing (BHS)

Before each release, there is a **Bug Hunting/Squashing (BHS)** cycle:
a period during which the staging environment tests the specific release candidate,
without mixing in features still under development. To achieve this, we fork an
ephemeral `release/x.y.z` branch from `develop`; it becomes the candidate to
replace `main`.

Acessilia and the [Toolbox](https://github.com/A11yDevs/acessilia-toolbox) run BHS
together, with the same version. **Cut the Toolbox first**: CI checks a
`release/x.y.z` branch against the capability contract of the Toolbox's
`release/x.y.z`.

1. **Cut** — at the start of the BHS:

   ```bash
   ./scripts/ops.sh bhs start 0.2.0
   ```

   The script forks `release/0.2.0` from `origin/develop`, commits the version
   bump (`pyproject.toml` and `uv.lock`) on it and pushes it, in a temporary
   worktree, so your checkout is left untouched. It refuses a version whose
   branch or `v` tag already exists.

2. **During BHS**:
   - `fix/*` (or `hotfix/*`) PRs that address bugs found in staging are targeted
     at `release/0.2.0` (instead of `develop`). The `release-scope` CI job
     rejects PRs from any other branch.
   - `feat/*`, `refactor/*` and other PRs continue targeting `develop` as
     usual—`develop` is never blocked, since the release scope was locked at the
     time of the cut.
   - The **CI pipeline** (`ci.yml`) runs the same tests on PRs to `release/**`.
   - The **CD pipeline** (`delivery.yml`) publishes the `release/0.2.0` image to GHCR
     with the tags `release-0.2.0` and `sha-<commit>`.

3. **Point Staging to the release** — on the staging server, in the clone
   (Toolbox first):

   ```bash
   ./scripts/ops.sh track release/0.2.0
   ```

   It checks out and pulls `release/0.2.0`, sets `TRACK_BRANCH` (and `TRACK_TAG`)
   in `.env` and updates, so staging runs the `release-0.2.0` image. Run
   `./scripts/ops.sh bhs status` from your machine to see the release's CI,
   image and PRs.

4. **Closing the BHS** — once the release is stable (close the Toolbox first:
   CI on `main` checks the Toolbox's `main` contract):

   ```bash
   ./scripts/ops.sh bhs finish 0.2.0            # opens release/0.2.0 → main and chore/sync-release-0.2.0 → develop
   # review and merge both PRs (release → main with "Create a merge commit")
   ./scripts/ops.sh bhs finish 0.2.0 --cleanup  # tags v0.2.0 on the merge into main, deletes the branches
   ```

   Fixes reach `develop` through `chore/sync-release-0.2.0`, forked from the
   release: resolve conflicts with `develop` there, never on `release/0.2.0`,
   which goes to `main`. Running the script again carries fixes merged
   afterwards over to the sync branch.

   Then, on the staging server, `./scripts/ops.sh track develop` goes back to
   tracking `develop` (only once the sync PR is merged: `track` refuses a branch
   without `scripts/ops.sh`).

### 5.2 Libraries in `libs/` (docstruct and SDK)

`libs/docstruct` (pure document-structure algorithms) and `libs/sdk` (access to
the Toolbox through its HTTP contract) are separate packages that live in this
repository. They follow the layering described in
[architecture.md](docs/architecture.md#libraries-and-the-toolbox-libs):

- **No imports upward.** `docstruct` imports nothing from `backend`, the SDK or
  `acessilia_toolbox`; the SDK imports neither `backend` nor
  `acessilia_toolbox`. Each library's `tests/test_purity.py` enforces it, and
  `tests/test_architecture_layers.py` keeps `backend` from importing the Toolbox
  package.
- **Run their own suites**, which CI also runs:
  `cd libs/docstruct && uv run --extra dev pytest` and `cd libs/sdk && uv run --extra dev pytest`.
- **Keep the READMEs in both languages.** `tests/test_docstruct_readme_sync.py`
  checks the docstruct pair.
- **docstruct is published for other repositories.** A change the Toolbox
  should receive needs a version bump and a `docstruct-vX.Y.Z` tag after the
  merge; see [Releases](libs/docstruct/README.md#releases). The Toolbox then
  moves to the new version in its own PR. The application release (section 6)
  does not publish docstruct, and a docstruct release does not touch the
  application.

### 6. Release (`release/*` → `main`)

Only maintainers ([@marceloakira](https://github.com/marceloakira),
[@jhonata192](https://github.com/jhonata192) and
[@fragaeduardo](https://github.com/fragaeduardo)) may merge a release into `main`.

1. **Did QA sign off on the BHS?** → proceed.
2. Run `./scripts/ops.sh bhs finish x.y.z`, which opens the Pull Request from
   `release/x.y.z` to `main`.
3. Ask another maintainer for review.
4. After approval, merge it with **"Create a merge commit"**: the release
   replaces `main`, and squash or rebase would discard its history.
5. The **CD pipeline** on `main` publishes tags `main`, `latest`, and `sha-<commit>`.
6. Promote the production environment as described in [docs/producao-systemd.md](docs/producao-systemd.md).

The version was already bumped on the release branch when it was cut. To cut
the **official release** with a semantic version:

```bash
# 1. Tag the merge into main (also deletes release/x.y.z and its sync branch)
./scripts/ops.sh bhs finish 0.2.0 --cleanup

# 2. The Release workflow (release.yml) builds and publishes 0.2.0, 0.2 and 0
#    to the GHCR, and creates a GitHub Release with an automatic changelog
```

After a release, merge `main` back into `develop`:

```bash
git checkout develop
git merge main
git push origin develop
```

### 7. Hotfixes (critical fixes)

Hotfixes follow the same PR flow — no direct pushes; CI creates the tag and release automatically.

```bash
git checkout main
git checkout -b hotfix/crash-upload
# make the fix
git commit -m "fix: fix crash when uploading a corrupted PDF"
git push origin hotfix/crash-upload
# Open a Pull Request from hotfix/crash-upload → main on GitHub
# After approval and merge, CI builds the main + sha-xxx image

# If it is severe enough to warrant an immediate release:
git tag v0.3.1 && git push origin v0.3.1

# Propagate into develop
git checkout develop
git merge main
git push origin develop
git branch -d hotfix/crash-upload
```

## Commit convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <description>

[optional body]
```

### Types

| Type | Use |
|------|-----|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation |
| `refactor` | Refactoring that does not change behavior |
| `test` | Tests |
| `chore` | Maintenance (deps, CI, config) |
| `style` | Formatting, linting |
| `perf` | Performance improvement |

### Examples

```
feat(api): adds EPUB export endpoint
fix(telegram): fix timeout on large files (>10MB)
docs(readme): update API usage examples
refactor(agents): extract OCR logic into a separate service
test(pipeline): add test for PDDL flow with docling
chore(deps): bump fastapi to 0.115
perf(ocr): reduce RapidOCR memory usage
```

## Versioning

We follow [Semantic Versioning](https://semver.org/):

```
vMAJOR.MINOR.PATCH
```

- **MAJOR**: breaking change to the public API
- **MINOR**: backward-compatible new feature
- **PATCH**: backward-compatible bug fix

## Team rules

1. **Never commit straight into `main`** — always use a branch + PR.
2. **Never commit straight into `develop`** — except merges of temporary branches.
3. **Always rebase before merging** to keep history linear.
4. **Branches are ephemeral** — they live only as long as the task needs them.
5. **Small, focused PRs** — easier to review and less conflict-prone.
6. **Atomic commits** — one commit = one complete logical change.
7. **Tests are mandatory** — every `feat` or `fix` must add or update tests.
8. **Run `pytest` before pushing** — make sure nothing is broken.

## Rulesets (branch protection)

The repository uses **GitHub Rulesets** to protect the `main` branch from deletion, force pushes, and unreviewed merges. Rulesets are configured **via the REST API**, not through files in the repo itself.

The file `.github/rulesets/main.json.example` holds a template of the current configuration. To apply or refresh the rulesets, run:

```bash
# Apply/update the rulesets via the GitHub API
./scripts/setup-rulesets.sh

# Only prints the payload without changing anything
DRY_RUN=1 ./scripts/setup-rulesets.sh
```

> **Important:** the ruleset allows bypasses by repository administrators (`RepositoryRole`), so maintainers can manage the branch without being blocked.

## Environment setup

```bash
# Clone and install dependencies
git clone git@github.com:A11yDevs/acessilia.git
cd acessilia
uv sync --extra dev   # uses the Python 3.11 pinned in .python-version

# Configure environment variables
cp .env.example .env

# Run the tests to check that everything is OK
uv run pytest
```

## Pull requests

1. Make sure your branch is up to date with `develop` (`git rebase origin/develop`).
2. Run `uv run pytest` and confirm all tests pass. Code, docs and the PR are written in English (constitution, principle 2.8): `tests/test_no_portuguese.py` fails on new Portuguese text anywhere in the repository. Intentional Portuguese (user-facing strings, detection patterns, `*.pt-br.md` mirrors) gets an exemption in that test. When you clean a file listed in `tests/fixtures/portuguese_allowlist.json`, lower its count there.
3. Fill in the [pull request template](.github/pull_request_template.md): why, what changes, how you verified it, and the **architecture conformance checklist** (principles P1–P9 of the [constitution](docs/constitution.md)).
4. Reference any related issues. `Closes #42` closes the issue only when the PR merges into `main`, the default branch; for a PR into `develop`, close the issue by hand after the merge.
5. Wait for review and adjust if needed.

## Continuous integration (CI/CD)

The CI/CD pipeline is defined by three workflows:

- **`.github/workflows/ci.yml`** — on every PR to `main`, `develop` or `release/**`, and after pushes to those branches, runs the core, docstruct and SDK test suites on Python 3.11 and rejects unexpected skipped tests.
- **`.github/workflows/delivery.yml`** — after CI passes on a push, builds the image, runs a health smoke test and a size guardrail, and publishes it to GHCR.
- **`.github/workflows/release.yml`** — when a maintainer creates a `v*` tag, builds, publishes and creates the GitHub Release.

| Workflow | Event | Action |
|----------|-------|--------|
| **CI** | PR to `main`, `develop` or `release/**` | Core, docstruct and SDK test suites |
| **CI** | Push to `main`, `develop` or `release/**` | Same suites, then Delivery |
| **Delivery** | CI completed on `main` | Build, smoke test + push: `main`, `latest`, `sha-xxx` |
| **Delivery** | CI completed on `develop` | Build, smoke test + push: `develop`, `sha-xxx` |
| **Delivery** | CI completed on `release/x.y.z` | Build, smoke test + push: `release-x.y.z`, `sha-xxx` |
| **Release** | `v*` tag created in git | Build, smoke test + push: `X.Y.Z`, `X.Y`, `X` + GitHub Release |

The following references are published in `ghcr.io/a11ydevs/acessilia`:

| Tag | Source branch | Purpose |
|-----|---------------|---------|
| `develop` | `develop` | Staging (refreshed by the systemd timer) |
| `main` | `main` | Production (CD) |
| `latest` | `main` | Production (tracks main with a moving ref) |
| `sha-<commit>` | `main` or `develop` | Immutable reference |
| `X.Y.Z` | git tag `v*` | Official versioned release |
| `X.Y`, `X` | git tag `v*` | Semantic alias of the most recent release in this line |

## Questions?

Open an [issue](https://github.com/A11yDevs/acessilia/issues) or start a [discussion](https://github.com/A11yDevs/acessilia/discussions).
