# Releasing memory-kernel

The release workflow at [.github/workflows/release.yml](../.github/workflows/release.yml) builds the sdist and a pure-Python wheel and publishes them to PyPI on every tag matching `v*.*.*`.

## One-time setup: trusted publishing

The workflow uses PyPI's [trusted publishing](https://docs.pypi.org/trusted-publishers/) so no API token is stored in GitHub.

1. Sign in to https://pypi.org/manage/project/amormorri-memory-kernel/settings/publishing/
2. Add a new trusted publisher with:
   - **Owner**: `Artem362`
   - **Repository name**: `memory-kernel`
   - **Workflow filename**: `release.yml`
   - **Environment**: `pypi`
3. In the GitHub repository settings, create an environment named `pypi` (Settings → Environments → New environment). No secrets are required; the environment just provides a deployment gate that you can later guard with required reviewers.

If you prefer to use a classic PyPI API token instead, replace the `permissions: id-token: write` block in the workflow with a token-based step:

```yaml
- name: Publish to PyPI
  env:
    TWINE_USERNAME: __token__
    TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
  run: |
    python -m pip install twine
    python -m twine upload dist/*
```

…and add `PYPI_API_TOKEN` to repository secrets.

## Cutting a release

1. Update [`CHANGELOG.md`](../CHANGELOG.md) with a new top-level entry.
2. Bump `version` in [`pyproject.toml`](../pyproject.toml).
3. Run the test suite locally: `python -m pytest`.
4. Commit the changes (e.g. `chore(release): 0.2.0`).
5. Tag the release: `git tag v0.2.0 && git push origin v0.2.0`.
6. The workflow runs on the tag push and uploads to PyPI.

The workflow can also be triggered manually via the **Actions** tab → **Release** → **Run workflow** for testing the build steps without publishing (use the staging variant, see below).

## Pre-release dry run

To test the build pipeline without touching PyPI, push a tag that does not match the trigger pattern (e.g. `dryrun-2026-05-10`) and run the workflow manually with `workflow_dispatch`. The `build` job will run; the `publish-pypi` job is gated by the `pypi` environment and will halt if no trusted publisher matches.

## What is NOT in the wheel today

The wheel published by this workflow is **pure Python** (`py3-none-any`). The optional Rust accelerator at [src/memory_kernel/_native.pyd](../src/memory_kernel/_native.pyd) is `.gitignore`-d, so CI checkouts never include it. End users who want the native acceleration build it from source via [scripts/build_native.ps1](../scripts/build_native.ps1) (or the equivalent on Linux/Mac).

Shipping platform-specific wheels with the native module pre-built would require switching the build backend from `hatchling` to `maturin` (or running both in parallel) and adding a per-OS / per-Python build matrix in CI. That is tracked as a separate gap in [`CHANGELOG.md`](../CHANGELOG.md).
