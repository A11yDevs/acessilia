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
poetry run pytest tests/ -v
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

The staging environment uses a systemd timer (`staging-update.timer`) that checks every 60s for a new image and restarts the container automatically. See [docs/homologacao-systemd.md](docs/homologacao-systemd.md) for detailed install and management instructions.

The full staging environment setup lives in:

- `docker-compose.staging.yml` — defines the container + Watchtower
- `scripts/staging-update.sh` — upgrade script
- `scripts/setup-homologacao.sh` — initial configuration script

```bash
# Check which image is live (via the health API)
curl http://homologacao:8000/api/v1/health | jq .

# Or manually pull a specific image to test it
 docker pull ghcr.io/a11ydevs/acessilia:sha-abc1234

# Verify which tag is running in the container
docker inspect acessilia-staging | jq '.[0].Config.Image'
```

The complete staging environment setup lives in:

- `docker-compose.staging.yml` — defines the container + Watchtower
- `scripts/setup-homologacao.sh` — initial configuration script

### 5.1 Bug Hunting/Squashing (BHS)

Before each release, there is a **Bug Hunting/Squashing (BHS)** cycle:
a period during which the staging environment tests the specific release candidate,
without mixing in features still under development. To achieve this, we create an
ephemeral `release/x.y.z` branch based on `develop`.

1. **Cut** — at the start of the BHS, cut the release branch from `develop`:

   ```bash
   git checkout develop && git pull
   git checkout -b release/0.0.1 origin/develop
   git push origin release/0.0.1
   ```

2. **During BHS**:
   - `fix/*` PRs that address bugs found in staging are targeted at `release/0.0.1`
     (instead of `develop`).
   - `feat/*` PRs continue targeting `develop` as usual—`develop` is never blocked,
     since the release scope was locked at the time of the cut.
   - The **CI pipeline** (`ci.yml`) runs the same slim/docling tests on PRs and pushes
     to `release/**`.
   - The **CD pipeline** (`delivery.yml`) publishes the `release/0.0.1` image to GHCR
     with the tags `release-0.0.1` and `sha-<commit>`.

3. **Point Staging to the release** — set `TRACK_BRANCH=release/0.0.1` in the
   staging server's `.env` file so that `scripts/staging-update.sh` starts tracking
   the release branch (image tag `release-0.0.1`) instead of `develop`:

   ```bash
   echo "TRACK_BRANCH=release/0.0.1" >> .env
   ```

4. **Closing the BHS** — once the release is stable:

   ```bash
   # Merge into main (generates the official release; see section 6)
   # Open a PR from release/0.0.1 to main and merge after approval

   # Propagate fixes to develop
   # Open a PR from release/0.0.1 to develop and merge after approval

   git push origin --delete release/0.0.1
   ```

   Then, remove (or revert) `TRACK_BRANCH` from the staging `.env` file so that staging
   goes back to tracking `develop`.

### 6. Release (`release/*` → `main`)

Only maintainers ([@marceloakira](https://github.com/marceloakira),
[@jhonata192](https://github.com/jhonata192) and
[@fragaeduardo](https://github.com/fragaeduardo)) may merge a release into `main`.

1. **Did QA sign off?** → proceed.
2. Open a Pull Request from `release/x.y.z` to `main` on GitHub.
3. Ask another maintainer for review.
4. After approval, merge it (preferably "Create a merge commit").
5. The **CD pipeline** on `main` publishes tags `main`, `latest`, and `sha-<commit>`.
6. Promote the production environment as described in [docs/producao-systemd.md](docs/producao-systemd.md).

To cut an **official release** with a semantic version:

```bash
# 1. Ensure the version in pyproject.toml has been updated on the release branch
#    (ex: 0.1.0 for branch release/0.1.0)
git checkout main && git pull

# 2. Create the semantic tag
git tag v0.1.0
git push origin v0.1.0

# 3. The Release workflow (release.yml) builds, publishes 0.1.0, 0.1, 0
#    and -slim variants to the GHCR, and creates a GitHub Release with an automatic changelog
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
poetry install

# Configure environment variables
cp .env.example .env

# Run the tests to check that everything is OK
poetry run pytest
```

## Pull requests

1. Make sure your branch is up to date with `develop` (`git rebase origin/develop`).
2. Run `poetry run pytest` and confirm all tests pass.
3. Clearly describe what the PR does and which problem it solves.
4. Reference any related issues (e.g.: `Closes #42`).
5. Wait for review and adjust if needed.

## Continuous integration (CI/CD)

The CI/CD pipeline is defined by three workflows:

- **`.github/workflows/ci.yml`** — runs the tests in two variants (`slim` and `docling`) on every PR targeting `main` or `develop`, as well as after pushes to those branches.
- **`.github/workflows/delivery.yml`** — once CI passes, builds and publishes Docker images to GHCR.
- **`.github/workflows/release.yml`** — when a maintainer creates a `v*` tag, it builds, publishes, and creates the GitHub Release.

| Workflow | Event | Action |
|----------|-------|--------|
| **CI** | PR against `main` or `develop` | Tests the slim and docling variants |
| **CI** | Push to `main` or `develop` | Tests the slim and docling variants |
| **Delivery** | CI completed on `main` | Build, smoke test + push: `main`, `latest`, `sha-xxx`, `main-slim`, `sha-xxx-slim` |
| **Delivery** | CI completed on `develop` | Build, smoke test + push: `develop`, `sha-xxx`, `develop-slim`, `sha-xxx-slim` |
| **Release** | `v*` tag created in git | Build, smoke test + push: `X.Y.Z`, `X.Y`, `X` and `-slim` variants + GitHub Release |

| Tag | Source branch | Purpose |
|-----|---------------|---------|
| `develop` / `develop-slim` | `develop` | Staging (refreshed by the systemd timer) |
| `main` / `main-slim` | `main` | Production (CD) |
| `latest` / `latest-slim` | `main` | Production (tracks main with a moving ref) |
| `sha-<commit>` / `sha-<commit>-slim` | `main` or `develop` | Immutable reference |
| `X.Y.Z` / `X.Y.Z-slim` | git tag `v*` | Official versioned release |
| `X.Y` / `X.Y-slim`, `X` / `X-slim` | git tag `v*` | Semantic alias of the most recent release in this line |

## Questions?

Open an [issue](https://github.com/A11yDevs/acessilia/issues) or start a [discussion](https://github.com/A11yDevs/acessilia/discussions).
