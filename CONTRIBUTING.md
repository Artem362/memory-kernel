# Contributing to Memory Kernel

Thanks for your interest! A few ground rules keep the project healthy.

## License and sign-off (DCO)

Memory Kernel is licensed under the Apache License 2.0 (see [LICENSE](LICENSE)).
By contributing, you agree that your contributions are licensed under the same terms.

We use the [Developer Certificate of Origin](https://developercertificate.org/).
Every commit must be signed off, which certifies that you wrote the change or
otherwise have the right to submit it:

```bash
git commit -s -m "Your change"
```

This adds a `Signed-off-by: Your Name <you@example.com>` line to the commit.
Pull requests with unsigned commits cannot be merged.

## Development setup

```bash
pip install -e .[dev]
python -m pytest
```

The optional Rust accelerator builds with `scripts/build_native.ps1` (Windows)
and is never required: every code path has a pure-Python fallback, and tests
must pass with `MEMORY_KERNEL_DISABLE_NATIVE=1` as well.

## What makes a good change

- Determinism is a feature. No fuzzy/ML-based retrieval in the core; ranking
  must stay explainable from the scoring function.
- Local-first is non-negotiable: no network calls from the core library.
- Hot paths that justify it can be mirrored in the Rust accelerator
  ([rust/src/lib.rs](rust/src/lib.rs)) — benchmark first
  (`scripts/benchmark_ingest.py`, `scripts/benchmark_upsert.py`).
- Ukrainian-language behavior is tested (`tests/test_stemmer.py`); changes to
  canonicalization or stemming need parity tests for both Python and Rust paths.
- New tools exposed over MCP must be non-destructive or reversible; permanent
  deletion stays CLI-only.

## Tests

`python -m pytest` must pass. New behavior needs tests; bug fixes need a
regression test that fails before the fix.
