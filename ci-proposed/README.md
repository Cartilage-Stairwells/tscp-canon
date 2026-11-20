# Proposed CI change, F09

`ci.yml` here is the full replacement for `.github/workflows/ci.yml` at pin
`0b141f414b7789701248944509ef420d848c8a2e`.

It sits outside `.github/` because the credential used to push this branch does not hold GitHub's `workflow`
scope, which is required to create or update workflow files. Nothing else about the change is blocked.

To apply: open `.github/workflows/ci.yml` on branch `gate/f09-pin` in the GitHub web editor, replace its
contents with this file, and commit. That commit triggers the first run.

Placeholders are already resolved: action pinned to `df2a88e9fe4098bad09cb42c3dec7187f15861fc`, channel
`nightly-2026-11-19`, which is the nightly published on the date of this change.
