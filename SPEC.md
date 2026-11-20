# Devil Painter: product specification

Author identity: Artbyo3.

## How to read this document

This specification describes where Devil Painter is going and the
invariants it keeps on the way. It is not a feature cap. Work that serves the
stated direction is in scope even when this document does not list it, and a
capability missing from these pages is unbuilt, not unwanted. Sections marked
**Direction** describe work that does not exist yet. Everything else describes
the product on `main` today.

## Product identity

Devil Painter is layer-based texture painting inside Blender, at full
behavioral parity with the dedicated layer-based texture painting
applications artists already use. Parity is the current phase and the target:
an artist coming from one of those applications should find every step of
their workflow, behaving the way they expect, without leaving Blender. A
Blender artist should be able to follow the same workflow without learning a
second program.

The product is past its MVP. Version 0.3.0 is the public announcement
release, shipped through the project's own Blender extension repository.

Devil Painter shares the Devil workspace with Devil Designer: the same shell,
tokens, icons, and interaction behavior, re-hued to Painter's pink-red
identity so the two products read as one family.

## Foundations

These are fixed points the product builds on. They enable the work; they are
not limits on it.

### License and platform

- Licensed GPL-3.0-or-later.
- Published through the project's own Blender extension repository, under
  these rules:
  - every shipped asset is CC0;
  - every permission the add-on uses is declared in the manifest;
  - no external binaries ship in the package;
  - no self-update: Devil Painter never updates its own code;
  - no telemetry.
- The network is used only for the optional asset packs (catalog, previews,
  and downloads). That use is declared as the manifest's network permission
  and is gated by Blender's Allow Online Access setting: with online access
  off, Devil Painter makes no network request.
- One package for everyone. There are no editions, unlocks, or per-user
  builds.
- Targets Blender 5.2 and newer.

### Blender is the engine

- Blender's own 3D viewport is the painting surface and Blender's texture
  paint brush engine rasterizes strokes. Devil Painter builds its tools on top
  of them, so every improvement Blender makes to its viewport and brushes
  reaches Devil Painter's artists. Bake, shader nodes, image I/O, Cycles, and
  undo are Blender's too.
- The interface is Devil Painter's own: every control is custom GPU-drawn.
  No native Blender panels, sidebars, popups, or dialogs. A native call is
  used only where the engineering requires it, such as an OS file or folder
  picker launched from a custom card. The `View3D > View > Devil Painter`
  launcher entry is the one standing native entry point.

### The document is the source of truth

The non-destructive layer document stored on the mesh is the single source of
truth. The live material preview and every exported texture are downstream
outputs of it, produced with one shared blending model, so what the artist
sees is what the artist exports.

## Product today

### Opening and projects

- `View3D > View > Devil Painter` or Ctrl+Alt+P opens the workspace over
  Blender's 3D viewport. The close button or Ctrl+Alt+P closes it, and
  Blender's header, tool header, toolbar, asset shelf, and navigation gizmo,
  hidden while it is open, come back.
- A start card sets up a project on the selected mesh: a project template,
  resolution, normal format and space, UDIM tiles, and an automatic unwrap
  for meshes without UVs. Starting switches the viewport to Material Preview and
  enters Texture Paint mode with a first paint layer.
- A project holds one texture set per material slot, each with its own
  resolution, channels, shader, transparency, UDIM tiles, and layer stack.
  Clicking faces in the viewport switches to their set.
- Project settings cover normal format, tangent mode, real-world scale, mesh
  reimport, autosave, and customizable shortcuts.
- Saving the `.blend` packs every layer image, channel canvas, mask, cache,
  and baked map. A scripting API exposes project, layer, bake, and export
  operations to Python.

### Document model

- Layers are addressed by a stable uid. The selection is a layer plus a
  target (content, mask, or one effect), so every new kind of layer or effect
  joins without changing how selection and undo work.
- Channels come from one registry: base color, roughness, metallic, normal,
  height, emission, opacity, ambient occlusion, flow map, and user channels.
  Each texture set chooses its channels; only enabled channels are previewed,
  listed, and exported. Each channel except base color stores its paint
  canvases at 8-bit, 16-bit, or 32-bit float, 8-bit by default. Deeper
  channels keep their precision through painting, saving, and export, where
  an output is written at least as deep as its deepest source channel that
  the file format allows.
- Every layer carries one slot per channel with its own enable, value or
  source, opacity, and blend mode. The blend set covers the full range artists
  expect from a dedicated painting application, including the normal-map
  combine and detail modes.
- Layer kinds:
  - Paint layers hold painted color plus a canvas per channel, so one stroke
    paints color, roughness, metallic, height, normal, and the rest together.
  - Fill layers drive each channel from a value, an image texture, or a
    procedural pattern.
  - Material layers are fills that remember the material they came from and
    can be replaced or reset.
  - Folders composite their children as a group and mix the result into the
    stack with Passthrough or any folder blend mode, per channel, with their
    own opacity and mask stack.
  - Instances mirror a source layer from another texture set, so editing the
    source updates every instance.
- Layers can be shown, hidden, isolated, renamed, reordered by dragging,
  nested, multi-selected, copied, pasted, duplicated, flattened, exported on
  their own, and moved or instanced between sets.

### Effect stacks

Layers carry two ordered stacks, applied in stack order, and folders carry
the mask stack.

- **Content stack**: Levels, Filter, Fill, Paint, and Generator effects,
  applied to every channel the layer writes. Fill, Paint, and Generator
  effects add content of their own and combine with the content below them
  through their blend mode and opacity.
- **Mask stack**: a painted mask (white or black), a geometry mask (picked
  faces or mesh parts), and Paint, Fill, Levels, Filter, Generator, Compare
  mask, Anchor, and ID color effects, each with its own blend mode from the
  full mask blend set and its own opacity. A quick mask paints a temporary
  mask and applies it to the selection, and the mask can be shown on the
  model.
- Levels work on all components or one at a time, with optional clamping.
- A Generator is the same effect in either stack. It reads the baked mesh
  maps (curvature, ambient occlusion, position, world normal, thickness,
  height, UV border distance) or works procedurally, with level, contrast,
  invert, a choice of breakup texture, and a weight per mesh term.
- Effects, folders, and smart assets save with the file and reopen
  unchanged. Documents saved by earlier versions open with the same result
  they had.

### Anchors

A Generator or Filter effect in either stack can take another layer's result
as an extra input, choosing the channel and the anchor strength. A Generator
adds the anchored channel to its signal as detail around mid-gray, so painting
the anchor pushes the generator up or down where it was painted. A Filter uses
the anchored value as its per-pixel strength. At zero strength, or with no
anchor, the effect renders exactly as it does unanchored. Anchors survive
saving, and smart materials keep anchors that point inside the saved subtree.

### Filters

- Filters span adjust, color, lighting, blur and sharpen, distort, and edge
  families, available in both stacks and from the shelf.
- Pointwise filters work on each pixel independently.
- Positional filters, the ones that read neighbouring pixels, process only
  what is below them in their stack. Effects above them composite afterwards
  and stay untouched. The result below each positional filter is baked to a
  cached texture at the set resolution, refreshed after strokes, edits, undo,
  and before every export, bake, and flatten, and packed on save.
- Height-aware filters read the height below them: slope blur blurs by how
  steep the height is, and height to normal writes a tangent-space normal
  from it in the project's normal format.

### Projections

Texture and pattern sources project by UV, tri-planar, planar, spherical, or
cylindrical mapping with tiling and an interactive 3D gizmo. Each projection
carries the controls an artist expects from it: UV offset and spin with an
option to repeat identically on every UDIM tile, tri-planar edge hardness, and
planar bend, corner warp, and snap to surface. Fill effects in the effect
stacks project by UV or tri-planar mapping with tiling and offset.

### Painting

- Tools: Paint, Erase, Fill, Blur, Smear, Clone, Polygon fill (triangle, face,
  mesh part, UV chunk, loop), and Path (ribbon or filled shape), plus Undo
  and Redo.
- Paint and Fill strokes land in a per-set stroke buffer that the material
  previews live; at stroke end it merges into the layer's color and every
  enabled channel canvas.
- Brushes are Devil Painter's own copies of Blender's essential brushes:
  color, size, opacity, flow, spacing, hardness, smoothing, jitter, pressure,
  stroke method, angle, symmetry and radial symmetry, normal tilt, stroke
  dynamics, a brush alpha, a stencil (image, vector, or text), material
  painting, and a value per channel the brush paints.
- The 2D view docks Blender's Image Editor in Paint mode beside the model,
  showing the selected canvas with its UV layout, painted by the same brush.

### Mesh maps

A bake card bakes ambient occlusion, curvature, thickness, position, world
normal, ID (by UV island, material, object, or vertex color), normal (from a
high-poly source or rounded edges from the mesh itself), height (from a
high-poly source), and UV border distance with Cycles. It supports high-poly
and cage objects, name matching, ray distance, samples, and automatic
rebaking. Baked maps show as thumbnails and can be viewed on the model.

### Compositing, preview, and export

- The stack compiles into the material's node tree for the live preview.
  Value edits update node inputs; structural edits rebuild the tree. The
  View menu shows the full material, any one channel, or any baked map.
- The viewport offers HDRI lighting, camera, color management, a path-traced
  preview, and post effects. None of these change exported values.
- Export bakes from the same compiled tree, so textures, patterns,
  projections, filters, and effects match the preview. It writes PNG, TGA,
  TIFF, or EXR at the bit depths each format supports, through built-in
  templates for common engines and formats or editable custom templates with
  packed outputs, with UDIM tiles, filename tokens, padding choices, a size
  override, and an optional hand-off to another application.
- The exported normal folds in the painted height, converted with the same
  math as the height to normal effect at the texture set's height strength and
  in the project's normal format. The Height output is still written on its
  own.
- Every baked mesh map (ambient occlusion, curvature, thickness, position,
  world normal, ID, normal, height, UV border distance) can be picked as an
  export source like any channel, with one entry per color component for the
  three-channel maps. An output that uses a mesh map that is not baked yet is
  skipped, and the export message names it and the map to bake.
- Export padding has a size and a style. Dilation, the default, repeats
  edge colors outward. Transparent leaves everything past the UV islands at
  zero alpha. Diffusion spreads each island's own edge colors outward, so
  the padding never takes colors from neighboring faces.

### Shelf, library, and packs

- The shelf holds rendered previews of materials, smart materials, textures,
  patterns, smart masks, generators, filters, brushes, alphas, and lighting,
  with search and filters for built-in and user assets. Clicking or dragging
  applies an asset.
- Any fill layer, layer, or folder saves to the user library as a material,
  smart material, or smart mask. User library folders and imported textures,
  `.blend` materials, PBR texture sets, and SVG stencils join the shelf.
- Packs are optional free CC0 asset collections listed in an online catalog:
  alphas, textures, `.blend` materials, brushes, and generators. Every
  download is checked against its published SHA-256 checksum before it
  installs, and only catalog entries hosted on the project's own release
  pages are accepted.

### Workspace

The custom-drawn workspace has fixed sections that new UI lands in: a
workspace bar, a tool strip, a tool dock, a shelf, the stage (the free
viewport area, which anchors toasts), and panels for Texture sets, Layers,
Properties, and Mesh maps. Sections dock to any side of the stage, split
into rows and columns, resize, collapse, and scroll, and the layout is
remembered across sessions. Properties
follows the selection. Popovers carry the color picker, dropdowns, context
menus, and cards. The UI is image-led: thumbnails and previews wherever an
image exists, text for names and values.

## Quality discipline

- **No regression means byte-identical exports.** For every behavior a change
  does not intend to touch, exported textures are identical byte for byte
  before and after the change. New controls default to the value that
  reproduces the previous output exactly, and documents saved by earlier
  versions reopen with the result they had.
- **Acceptance is the owner's hands-on use.** Automated suites, real-Blender
  load, draw, and end-to-end gates, static checks, and reviews are the floor a
  build must clear before the owner tests it. They never replace that test.
- **Motion and interaction changes carry GIF evidence** in their pull request,
  cropped to the interaction.
- Code carries no comments, docstrings, dead code, or unused imports; the
  checks in `tools/` enforce this on every build.
- Packages are reproducible archives in `dist/`, validated by Blender's
  extension validator and loaded in a real Blender before anything is called
  ready.
- `devil_painter/` holds only add-on runtime code and its manifest, `tests/`
  holds automated and real-Blender verification, and `tools/` holds packaging
  and repository checks.

## Direction

**Direction.** Nothing in this section exists on `main` yet unless it says
so. It is where the product is going, organized in the parity waves the
issue tracker follows. The waves set an order, not a boundary: anything that
brings the product closer to parity, or past it, belongs here.

Waves 1 to 3 (blend and mask parity, effect stacks and anchors, positional
filters) are on `main`.

- **Wave 4, projection and sampling.** UV offset and spin and tri-planar
  hardness are on `main`; texture wrap and filtering complete the wave.
- **Wave 5, brushes.** Pen pressure for flow, hardness, and angle; separate
  size, flow, and angle jitter; brush angle that follows the stroke path;
  world-space brush size; shift-click straight lines; dragging the stencil in
  the viewport; material brush textures projected along the stroke; clone in
  screen and 3D space.
- **Wave 6, channels and export.** More user channels; additional PBR
  channels and shaders; per-channel bit depth up to 32-bit float; height
  folded into the exported normal; mesh maps as export sources; padding and
  dilation styles; specular-glossiness outputs; layered PSD export.
- **Wave 7, baking.** Background baking with progress and cancel; bake
  anti-aliasing; per-map settings; choosing which texture sets to bake; a
  bake resolution separate from the texture set.
- **Wave 8, workflow and viewport.** Dropping materials onto the mesh in the
  viewport; dragging textures onto channel slots; importing files dropped
  from the OS; instances of folders and within the same set; one unified undo
  with a history panel; height displacement in the preview; rotating the
  environment by dragging.
- **Further out.** Particle brushes; strokes that re-render when the
  resolution changes, so smart materials become resolution-independent; a
  final-render view with image output; procedural material import within the
  no-external-binaries foundation. These are sequenced after the waves, not
  ruled out.

Beyond parity, the product keeps going wherever artists' texture painting
work in Blender takes it: faster time to a first painted texture, richer
image-led previews, and workflows that only make sense because the painting
lives inside Blender.
