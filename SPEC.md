# Devil Painter: product specification

This records the requested target for future development. It is not a claim that
all features below are complete or production-ready. Author identity: Artbyo3.

## Product direction

Bring non-destructive, layer-based texture painting directly inside Blender, in
the same Devil workspace as Devil Designer. Blender's own 3D viewport stays the
painting surface and Blender's native texture paint brushes do the painting.
Devil Painter adds the layer stack, the tools around it, and texture export.

A separate 3D viewport inside Devil Painter's window was considered and
rejected. Blender can draw a scene into an offscreen texture, but its brushes
only paint in a real viewport region. A custom viewport would need its own
brush engine, projection, and undo, which would be slower and weaker than
Blender's native painting.

## MVP scope

- Extension package `devil_painter` targeting Blender 5.2+, opened from
  `View3D > View > Devil Painter` or Ctrl+Alt+P. No sidebars or docked panels.
- Start painting on the selected mesh at 1K, 2K, or 4K. Meshes without UVs are
  unwrapped automatically. The mesh gets a Devil Painter material, the viewport
  switches to Material Preview, and the object enters Texture Paint mode with a
  first paint layer selected.
- Layer stack stored on the mesh object, so Blender undo and saving cover it:
  - Paint layers: one RGBA image. Painted color is the layer color and painted
    alpha is its coverage, so one stroke paints base color, roughness, and
    metallic together.
  - Fill layers: a constant color, roughness, and metallic.
  - Every layer: visibility, opacity, blend mode (Normal, Multiply, Screen,
    Overlay, Add) for color, per-channel enable for color, roughness, and
    metallic, rename, reorder, and delete.
  - Masks: white or black, painted with the same brushes. Painted alpha reveals
    the layer.
- Tools: Paint, Erase, Fill, Blur, Smear, and Clone from Blender's essential
  brushes, plus Undo and Redo. The brush strip edits the color, size, and
  strength the active brush actually uses.
- Live preview: the stack compiles into the material's node tree. Value edits
  update node inputs without recompiling. Structural edits rebuild the tree.
- Export: Base Color (sRGB), Roughness, and Metallic PNGs composited with the
  same math as the preview.
- Saving packs every layer image and mask into the `.blend`.

## Not in the MVP

- Normal and height channels, and painting them.
- Generators and smart masks driven by curvature, ambient occlusion, or
  position, and baking those maps.
- Multiple texture sets per object, UDIMs, and keeping other materials on a
  multi-material mesh. Start painting replaces the mesh's material slots.
- Smart materials, presets, and a material library.
- A 2D texture view inside the workspace.
- Scrolling for very long layer stacks; rows that do not fit are hidden.

## Architecture requirements

1. Keep `devil_painter/` strictly reserved for add-on runtime code and manifest,
   `tests/` for automated unit and real-Blender verification, and `tools/` for
   packaging and repository checks.
2. Enforce zero-comment / zero-docstring discipline (`tools/check_comments.py`),
   import and dead-code integrity (`tools/check_dead_code.py`), and publication
   hygiene (`tools/check_public.py`) from the first commit.
3. Package reproducible extension archives in `dist/` via `tools/build.py` and
   verify them with Blender's extension validator and headless smoke test.
4. The layer stack is the source of truth. The material node tree and exported
   PNGs are downstream outputs built from it with one shared blending model.

## MVP acceptance examples

- Build `dist/devil_painter-0.1.0.zip` cleanly via `python tools/build.py`.
- Validate the packaged extension archive with `blender --command extension validate`.
- Enable `devil_painter` in headless Blender and confirm its operators, menu
  entry, and layer stack property register and unregister without errors.
- In a real Blender window, open Devil Painter, start painting the default cube,
  paint a stroke, add a fill layer and set its metallic, hide and show it, add a
  black mask and paint it, export textures and confirm metallic appears only
  where the mask was painted, save with packed layers, reorder layers, switch
  tools, and close.
