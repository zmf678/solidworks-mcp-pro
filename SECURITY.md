# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.20.x | Yes |
| Older 0.x | No |

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's
private vulnerability reporting:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Include the version, a minimal reproduction and the impact.

If private reporting is unavailable, contact the maintainer through the GitHub
profile listed in the repository.

## Scope

SolidWorks MCP is a local desktop automation server:

- It talks to a running SOLIDWORKS instance over COM.
- The server itself makes no network calls and stores no credentials.
- It exposes a fixed set of typed MCP tools; there is no arbitrary-code or shell
  tool.

Relevant risks include:

- opening or importing untrusted CAD files (a malformed STEP/STL/3MF can crash
  SolidWorks or exhaust memory);
- writing exports or screenshots to attacker-controlled paths;
- modal SolidWorks dialogs blocking a call until the 120-second timeout.

Do not run the server against files or paths you do not trust. Report path
handling, injection, secret-handling or denial-of-service issues privately.

## Dependency and release hygiene

- Dependencies are pinned in `uv.lock`; Dependabot watches `pyproject.toml` and
  GitHub Actions.
- CI runs lint, type checks, unit tests and a package build on every PR.
- This fork does not publish to PyPI or the public MCP Registry.
