# Security Policy

## Supported version

Security fixes are applied to the latest commit on the `main` branch.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub Security Advisories:

<https://github.com/Mr-funny/gemini-flow-suite/security/advisories/new>

Do not include real Google cookies, Chrome profiles, account screenshots, generated history, proxy credentials, or Docker volume exports in a public Issue.

A useful report contains:

- A concise description and impact.
- Reproduction steps using redacted or synthetic data.
- The affected commit, operating system and Docker version.
- Logs with tokens, cookies, account identifiers and local paths removed.

## Local security model

Gemini Flow Suite is designed for a single trusted user on a local workstation.

- noVNC is bound to `127.0.0.1` by default.
- Google authorization is persisted in the Docker named volume `gemini-flow-suite-data`.
- Host Chrome profiles are stored below `~/.gemini-flow-suite`.
- The configured workspace is mounted read-only.
- The output directory is the only default read-write host bind mount.

Do not expose the noVNC port, Chrome debugging ports, Docker socket or authorization volume to an untrusted network or user.
