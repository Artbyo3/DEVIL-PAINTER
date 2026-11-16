# Devil Painter: product specification

This records the requested target for future development. It is not a claim that
all features below are complete or production-ready. Author identity: Artbyo3.

## Product direction

Bring non-destructive, layer-based texture painting directly inside Blender.
At the current validation stage, this repository establishes only the add-on
package structure, extension manifest, build/check tooling, and headless Blender
load verification.

## Validation-stage scope

- Extension package `devil_painter` targeting Blender 5.2+.
- Valid `blender_manifest.toml` metadata, permissions declaration, and build
  exclusion rules.
- Lifecycle registration (`register` / `unregister`) with one minimal 3D View
  sidebar panel (`DEVIL_PAINTER_PT_main`) confirming the add-on loads and
  registers cleanly.
- No texture-painting, layer-stack, brush, mask, or export implementation yet.

## Architecture requirements

1. Keep `devil_painter/` strictly reserved for add-on runtime code and manifest,
   `tests/` for automated unit and real-Blender verification, and `tools/` for
   packaging and repository checks.
2. Enforce zero-comment / zero-docstring discipline (`tools/check_comments.py`),
   import and dead-code integrity (`tools/check_dead_code.py`), and publication
   hygiene (`tools/check_public.py`) from the first commit.
3. Package reproducible extension archives in `dist/` via `tools/build.py` and
   verify them with Blender's extension validator and headless smoke test.

## Validation acceptance examples

- Build `dist/devil_painter-0.1.0.zip` cleanly via `python tools/build.py`.
- Validate the packaged extension archive with `blender --command extension validate`.
- Enable `devil_painter` in headless Blender and confirm `DEVIL_PAINTER_PT_main`
  registers and unregisters without errors.
