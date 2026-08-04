# Contributing to SwarmMesh

Thanks for considering a contribution. SwarmMesh has two official implementations of the
same protocol (see `docs/protocol.md`) — `python/` and `node/` — kept behaviorally
identical on purpose, so pick whichever matches the change you're making.

## Ground rules

- **No unverified claims.** Every README claim, benchmark number, and comparison-table
  cell must be reproducible from a real command someone can run. If you can't verify it,
  don't write it.
- **Protocol changes touch both implementations.** A change to `docs/protocol.md` is not
  complete until both `python/` and `node/` implement it identically and both test suites
  cover it.
- **Ranking claims stay honest.** The default memory-query ranking is keyword/BM25-style
  term-frequency scoring, not semantic search. Don't describe it as "AI-powered" or
  "semantic" search anywhere in code, docs, or commit messages unless a real embedding
  backend is actually wired in for that code path.

## Development setup

### Python (`python/`)
```bash
cd python
pip install -e ".[dev]"
pytest
ruff check .
mypy swarmmesh_cli
```

### Node (`node/`)
```bash
cd node
npm install
npm test
npm run lint
npm run typecheck
```

## Pull requests

- One logical change per PR.
- Add or update tests for any behavior change — a regression test per bug fix, a unit
  test per new feature.
- Run both test suites if your change touches `docs/protocol.md` or shared behavior.
- CI must pass (lint, types, tests, security scan) before review.

## Security

Found a vulnerability? Please do not open a public issue. See `SECURITY.md` for the
private disclosure process.
