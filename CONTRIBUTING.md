# Contributing to Acessilia

Thanks for considering a contribution! This document defines the project's guidelines based on a **simplified Git Flow**, designed to keep the agility typical of open-source projects.

You can also read these guidelines in **Brazilian Portuguese**: [português brasileiro](CONTRIBUTING.pt-br.md)

## Branching model

```
main  ──────────────●──────────────────●──  (stable versions)
   \              /  \                /
    develop ─────●─── release/x.y.z ─●────  (integration / BHS)
        \        /  \       |       /
         feat/* ──   fix/* ─┴──────
```
    
### Internationalization Changes

Internationalized the code and the documnentation.
See docs/i18n.md (English) and docs/i18n.pt-br.md (Portuguese) for implementation details.

Currently supported locales:
- en_US: This is the new default for the code
- pt_BR: This is fully supported and selectable (see LOCALE in `.env.example`)

Strings that are included in the i18n work and are now localized:
- Python code comment text
- Python code output strings
- Telegram bot slash commands and their responses
- HTML pages shown to one or more users that contain natural language text
- Email subjects and email body text
- Text document structure pagination label words
- Documents such as README.md and CONTRIBUTING.md now contain US English text, and the Portuguese text is contained in separate files such as README.pt-br.md and CONTRIBUTING.pt-br.md. Links from one document to the next hyperlink the user to the equivalent in their chosen language.

What this pull request did not internationalize, what remained unchanged:
- All Telegram bot slash commands that had command words in Portuguese are still working in the form of the Portuguese command words, because that is a user-facing interface. English word slash command equivalents were added so that people who know some English words but who do not know Portuguese have an alternative, and so that native English speakers can easily operate the bot.
- SQL schema symbols that were initially chosen as Portuguese words are unchanged. Those words will probably not be meaningful to non-Portuguese speakers, and may also be confusing or frustrating for English speaker software engineers.
- AI prompt text, because it is not user visible, and may be sensitive to translations. We know the prompts that are currently there work well, or at least we know how well they work. Those should be more closely reviewed to determine which are safe to translate into English, because international developers who expect English will otherwise find Portuguese AI prompt text.
- There are some regular expressions that match on Portuguese words, but changing these to English would likely change the behavior of the code. A deeper review of each of these should be done.
- Generation of audio is still in Brazilian Portuguese. Supporting speech output in more languages is a new separate feature to add.### Internationalization Changes

Internationalized the code and the documnentation.
See docs/i18n.md (English) and docs/i18n.pt-br.md (Portuguese) for implementation details.

Currently supported locales:
- en_US: This is the new default for the code
- pt_BR: This is fully supported and selectable (see LOCALE in `.env.example`)

Strings that are included in the i18n work and are now localized:
- Python code comment text
- Python code output strings
- Telegram bot slash commands and their responses
- HTML pages shown to one or more users that contain natural language text
- Email subjects and email body text
- Text document structure pagination label words
- Documents such as README.md and CONTRIBUTING.md now contain US English text, and the Portuguese text is contained in separate files such as README.pt-br.md and CONTRIBUTING.pt-br.md. Links from one document to the next hyperlink the user to the equivalent in their chosen language.

What this pull request did not internationalize, what remained unchanged:
- All Telegram bot slash commands that had command words in Portuguese are still working in the form of the Portuguese command words, because that is a user-facing interface. English word slash command equivalents were added so that people who know some English words but who do not know Portuguese have an alternative, and so that native English speakers can easily operate the bot.
- SQL schema symbols that were initially chosen as Portuguese words are unchanged. Those words will probably not be meaningful to non-Portuguese speakers, and may also be confusing or frustrating for English speaker software engineers.
- AI prompt text, because it is not user visible, and may be sensitive to translations. We know the prompts that are currently there work well, or at least we know how well they work. Those should be more closely reviewed to determine which are safe to translate into English, because international developers who expect English will otherwise find Portuguese AI prompt text.
- There are some regular expressions that match on Portuguese words, but changing these to English would likely change the behavior of the code. A deeper review of each of these should be done.
- Generation of audio is still in Brazilian Portuguese. Supporting speech output in more languages is a new separate feature to add.──●───●──────────────●────  (integration)
        \        /      \          /
         feat/* ──       fix/* ────
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
| `fix/*` | Correção de bug | `develop` | `develop` (or `release/*` during BHS, ver [section 5.1](#51-bug-huntingsquashing-bhs)) |
| `docs/*` | Documentation | `develop` | `develop` |
| `refactor/*` | Refactor | `develop` | `develop` |
| `chore/*` | Maintenance (deps, CI, config) | `develop` | `develop` |
| `release/*` | Release stabilisation (BHS cycle) | `develop` | `main` e `develop` |
| `hotfix/*` | Critical fix in production | `main` | `main` e `develop` |

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

Before each release, there is a cycle of **Bug Hunting/Squashing (BHS)**: a period
where staging t tests the release candidate exactly as is, without mixing in features
that are still under development. To do this, we create an ephemeral branch. `release/x.y.z`
based off of `develop`.

1. **Cut** — At the start of the BHS, cut the release branch based on `develop`:

   ```bash
   git checkout develop && git pull
   git checkout -b release/0.0.1 origin/develop
   git push origin release/0.0.1
   ```

2. **During BHS**:
   - PRs `fix/*` that fix bugs found in staging go to `release/0.0.1`
     (instead of `develop`).
   - PRs `feat/*` continue targeting `develop` normally — `develop` is never
     blocked, as the release scope was already locked at the outset.
   - **CI** (`ci.yml`) run the same slim/docling tests on PRs and
     pushes to `release/**`.
   - **CD** (`delivery.yml`) publishes an image of `release/0.0.1` in
     GHCR with the tags `release-0.0.1` and `sha-<commit>`.

3. **Staging points to the release** — it sets `TRACK_BRANCH=release/0.0.1` in
   `.env` of the staging server so that `scripts/staging-update.sh` switches to
   tracking the release branch (tag of the image `release-0.0.1`) instead of
   `develop`:

   ```bash
   echo "TRACK_BRANCH=release/0.0.1" >> .env
   ```

4. **Completion of BHS** — once the release is stable:

   ```bash
   # Merge into main (generates the official release, see section 6)
   # Open a PR de release/0.0.1 → main and merge after approval

   # Propagate the fixes to develop
   # Open a PR of release/0.0.1 → develop and merge after approval

   git push origin --delete release/0.0.1
   ```

   After, remove (or revert) `TRACK_BRANCH` of `.env` of staging so that
   staging returns to tracking `develop`.

### 6. Release (develop → main)

Only maintainers ([@marceloakira](https://github.com/marceloakira),
[@jhonata192](https://github.com/jhonata192) and
[@fragaeduardo](https://github.com/fragaeduardo)) may merge `develop → main`.

1. **Did QA sign off?** → proceed.
2. Open a Pull Request from `develop` to `main` on GitHub.
3. Ask another maintainer for review.
4. After approval, merge it (preferably "Create a merge commit").
5. The **CD pipeline** on `main` publishes tags `main`, `latest`, and `sha-<commit>`.

To cut an **official release** with a semantic version:

```bash
# 1. Bump the version in pyproject.toml
#    (e.g.: "0.2.0" → "0.3.0")
git checkout main && git pull
# edit pyproject.toml
git add pyproject.toml
git commit -m "chore(release): bump to 0.3.0"

# 2. Create the semantic tag
git tag v0.3.0
git push origin main --tags

# 3. The Release workflow (release.yml) builds, publishes v0.3.0 to GHCR,
#    and creates the GitHub Release with an automatic changelog
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
| **Release** | `v*` tag created in git | Build, smoke test + push: `vX.Y.Z`, `vX.Y.Z-slim` + GitHub Release |

The following refs are published for `ghcr.io/a11ydevs/acessilia`:

| Tag | Source branch | Purpose |
|-----|---------------|---------|
| `develop` / `develop-slim` | `develop` | Staging (refreshed by the systemd timer) |
| `main` / `main-slim` | `main` | Production (CD) |
| `latest` / `latest-slim` | `main` | Production (tracks main with a moving ref) |
| `sha-<commit>` / `sha-<commit>-slim` | `main` or `develop` | Immutable reference |
| `vX.Y.Z` / `vX.Y.Z-slim` | git tag `v*` | Official release |

## Questions?

Open an [issue](https://github.com/A11yDevs/acessilia/issues) or start a [discussion](https://github.com/A11yDevs/acessilia/discussions).
