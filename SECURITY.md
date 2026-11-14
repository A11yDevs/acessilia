# Security policy

You can also read this document in **Brazilian Portuguese**: [português brasileiro](SECURITY.pt-br.md).

## Supported versions

Only the latest deployed release of the core receives security fixes.

| Version | Supported |
|---|---|
| 0.2.x | ✅ |
| Older than 0.2 | ❌ |

The SDK, docstruct and the Toolbox follow the release they ship with.

## Reporting a vulnerability

**Do not open a public issue with exploit details or a proof of concept.**

Use GitHub's **private vulnerability reporting**:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Describe the issue, the affected component and version, and the steps to reproduce it. Include the impact and any suggested fix if you have one.

If the **Report a vulnerability** button is unavailable, open a minimal issue asking the maintainers for a private channel; do not include technical details in that issue.

Useful reports include a minimal reproduction, the commit or image tag tested, and whether the issue is exploitable without credentials. Never include real credentials, personal documents or third-party data; use synthetic samples.

## What is in scope

- the core API and processing pipeline (`backend/`, `frontend/`, `schemas/`);
- the public SDK (`libs/sdk`), docstruct (`libs/docstruct`) and their release artifacts;
- the Docker image, compose files and deployment scripts in this repository;
- dependency and supply-chain issues in the artifacts this repository publishes.

The Toolbox is a separate repository; report its issues there, or here if the problem is in how this repository consumes it. Vulnerabilities in third-party services and the Telegram platform are out of scope.

## Our process

- We acknowledge a report within **3 business days**.
- We triage it and confirm the severity and affected versions within **10 business days**.
- We keep the reporter informed while a fix is prepared and coordinate disclosure after a release.
- We credit reporters in the advisory unless they prefer to stay anonymous.

CI runs a dependency audit, CodeQL and a container image scan; a new high-severity finding fails the build unless a reviewed exception is recorded. Secret scanning and push protection are expected to be enabled in the repository settings.
