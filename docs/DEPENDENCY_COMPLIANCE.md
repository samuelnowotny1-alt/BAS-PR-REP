# Dependency Compliance

This project currently depends on standard open-source Python packages such as
`pydantic`, `fastapi`, `sqlalchemy`, `pandas`, `jinja2`, and related tooling.

## Current posture

- No full software composition analysis report is checked into the repository.
- A quick metadata pass shows mostly permissive upstream licenses such as MIT,
  BSD, and Apache-2.0.
- That is encouraging, but it is not a substitute for a release-grade notice
  bundle.

## Release checklist

Before distributing this software outside your own controlled environment:

1. Generate a pinned dependency inventory from the actual build environment.
2. Capture each package version and license.
3. Preserve any required copyright and attribution notices.
4. Include third-party notices with the distributed artifact when required.
5. Re-run the inventory whenever dependencies change.

## Important limitation

Package metadata is not always complete or normalized. For any serious
commercial release, verify licenses with a proper software composition analysis
tool or counsel-reviewed release checklist.
