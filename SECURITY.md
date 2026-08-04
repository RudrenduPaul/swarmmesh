# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately via GitHub's
[Security Advisories](https://github.com/RudrenduPaul/swarmmesh/security/advisories/new)
for this repository, rather than opening a public issue. Include reproduction steps and
the affected version (Python `swarmmesh-cli` on PyPI, Node `swarmmesh-cli` on npm, or
both). We aim to acknowledge reports within 5 business days.

## Scope note

SwarmMesh's HTTP and WebSocket server has no built-in authentication in v1 (see
`docs/protocol.md`). It is designed to run on `localhost` or inside a private network
alongside the agents it coordinates — the same trust boundary as a local Redis instance
or a SQLite file, not a public-internet-facing service. Running a SwarmMesh server
directly exposed to the public internet without a reverse proxy adding authentication is
a misconfiguration, not a supported deployment, and reports about that specific scenario
will be triaged as a documentation gap rather than a code vulnerability unless a real
authentication bypass is demonstrated.
