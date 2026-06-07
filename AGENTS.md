# AGENTS.md

Repository-wide instructions for coding agents working in this project.

## Scope
These rules apply to the whole repository.

## Release And Versioning Expectations
1. Any user-visible feature, behavior change, or removal must include a manifest version bump in `custom_components/octopus_germany/manifest.json`.
2. Keep `RELEASE_NOTES.md` in sync with the manifest version.
3. The top release section format must stay:
   - `## Version X.Y.Z (YYYY-MM-DD)`
4. Add a concise but complete changelog entry for:
   - new features
   - fixes
   - removed/deprecated functionality
   - workflow/release automation changes (if relevant)

## GitHub Release Workflow Expectations
1. Do not break `.github/workflows/tag-and-release.yaml`.
2. The workflow is expected to:
   - create a tag from manifest version
   - build release body from the matching `RELEASE_NOTES.md` section
   - append auto-generated notes as supplemental information
3. Keep YAML-safe shell blocks in workflow scripts (avoid indentation-sensitive heredoc mistakes).

## Current Product Decisions (Important)
1. Keep EV sensors:
   - SoC (`..._soc`)
   - Battery Size (`..._battery_size`)
2. Do not re-introduce removed sensors unless explicitly requested:
   - SoC Change (`..._soc_change`)
   - SoC Limit (`..._soc_limit`)

## Data Privacy And Safety
1. Never commit real user account identifiers, tokens, passwords, or personal logs.
2. Use sanitized examples in docs (for account numbers, IDs, etc.).

## Documentation Expectations
1. Keep both docs in sync when entity behavior changes:
   - `README.md`
   - `custom_components/octopus_germany/README.md`
2. If release behavior changes, document it in `RELEASE_NOTES.md`.

## Operational Notes
1. `.devcontainer-lock.json` is intentionally not required for this repo workflow.
2. Prefer minimal, focused changes over broad refactors.
