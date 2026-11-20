# User Guide

Devil Painter renders a custom, uncluttered painting workspace over Blender's 3D Viewport while keeping Blender's viewport shading and native texture paint brushes as the painting engine.

## Workspace Layout

The workspace surrounds the 3D Viewport stage. Every section and panel can be dragged by its header or empty space to dock on any side or split into columns and rows, resized at its border up to `1400 px`, and saved across sessions (right-click empty workspace space for **Reset layout**). By default, the layout is arranged as:

- **Workspace bar (top):** Active mesh, texture set, resolution, and active UDIM tile, **Project**, **Viewport**, **2D view**, **Bake maps**, **Channels**, **View** mode, **Export textures**, and **Close**.
- **Tool strip (below workspace bar):** Active tool, brush color swatch (HSV + Hex + Eyedropper), **Size**, **Opacity**, **Brush alpha**, **Brush** popover, **Symmetry**, **Stencil**, quick per-channel brush controls, and **Quick mask** (switches to **Polygon fill** or **Path** options when those tools are active).
- **Tool dock (left):** **Paint**, **Erase**, **Fill**, **Blur**, **Smear**, **Clone**, **Polygon fill**, **Path**, **Undo**, and **Redo**.
- **Shelf (bottom, collapsible):** **Materials**, **Smart**, **Textures**, **Patterns**, **Masks**, **Generators**, **Filters**, **Brushes**, **Alphas**, **Lighting**, and **Packs**, with search, **All** / **Built-in** / **Mine** filters, saved searches, and **Libraries**.
- **Right column:** Collapsible, scrollable **Texture sets**, **Layers**, **Properties**, and **Mesh maps** panels.

## Texture Sets and Channels

A project creates one texture set per material slot on the mesh, each with its own layer stack, resolution (`1024`, `2048`, or `4096` px), visibility toggle, and optional **UDIM** tiles. Clicking faces in the 3D Viewport switches to that texture set. Use **Project** in the workspace bar to set **Normal map** format (**OpenGL** / **DirectX**), **Tangent mode**, **Real-world scale**, per-set **Shader** (**Principled PBR** / **Unlit** / **Spec / gloss**) and **Transparency**, **Autosave**, **Strokes cross UV tiles**, mesh **Reimport**, and **Shortcuts**.

Use **Channels** in the workspace bar to enable or disable any of the **28** channels (with **Apply to every texture set** to update all sets at once):

- **Base Color** (sRGB)
- **Roughness**, **Metallic**, **Normal**, **Height**, **Opacity**, and **Ambient Occlusion** (Non-Color)
- **Emission** (sRGB)
- **Diffuse** and **Specular** (sRGB), **Glossiness**, **Displacement**, **Anisotropy level**, **Anisotropy angle**, **Transmission**, **Scattering**, **Sheen**, **Coat**, and **IOR** (Non-Color)
- **Flow map** and **User 1–8** (Non-Color, export only)

Use the **View** menu to switch between the full shaded **Material**, any enabled solo channel, or any baked mesh map.

## Layers, Folders, and Masks

- **Paint layers:** Store Base Color and per-channel painted canvases so **Paint**, **Erase**, **Fill**, **Blur**, **Smear**, and **Clone** operate across all enabled brush channels through the stroke buffer.
- **Fill layers:** Drive each channel independently from a **Value**, **Texture** (with **Wrap**: **Repeat**, **Clamp**, or **Mirror**, and **Filtering**: **Linear**, **Closest**, or **Cubic**), or **Pattern** using **UV** (with **Offset X**, **Offset Y**, and **Spin**, plus optional **Same on every UV tile** for UDIMs), **Tri-planar** (with **Hardness** for how softly its three sides blend), **Planar** (with bend, corner warp, and snap to surface), **Spherical**, or **Cylindrical** projection with an interactive 3D gizmo and adjustable **Tiling**.
- **Material layers:** Fill layers created from a shelf material remember their material definition and offer **Replace** and **Reset** actions in **Properties**.
- **Folders & Instances:** Folders group layers using **Passthrough** or any layer blend mode with shared opacity, visibility, and masking. Layers can also be **instanced** across texture sets so edits to the source update the instance.
- **Masks, Effect Stacks & Geometry Masks:** Layers and folders support a painted mask, a **Generator**, a **Geometry mask** (picked faces or mesh parts), and ordered **Mask effects** (**Paint**, **Fill**, **Levels**, **Filter**, **Compare mask**, **Anchor**, **ID color**) plus **Content effects** (**Paint**, **Fill**, **Levels**, **Filter**, **Generator**). A **Generator** or **Filter** effect can also take another layer as an **Anchor** input that shapes it. **Quick mask** lets you paint a temporary mask and apply it to the selected layer.
- **Layer actions:** Click to select, <kbd>Ctrl</kbd>/<kbd>Shift</kbd>-click to multi-select, drag to reorder or nest in folders, <kbd>Ctrl</kbd>+<kbd>C</kbd>/<kbd>Ctrl</kbd>+<kbd>V</kbd> to copy/paste, double-click to rename inline, and right-click for context actions (duplicate, group, flatten, export flattened/mask, instance or move between sets, save as material/smart material/smart mask, delete). Note known issue **#149**: undoing a layer deletion can restore the layer blank.

## Mesh Map Baking & Mask Generators

Open **Bake maps** in the workspace bar to bake up to **9** mesh maps directly with Cycles: **Ambient occlusion**, **Curvature**, **Thickness**, **Position**, **World normal**, **ID** (from **UV islands**, **Materials**, **Objects**, or **Vertex colors**), **Normal** (from high-poly, or rounded edges from the mesh itself), **Height** (from high-poly), and **UV border distance**.

Select **High-poly** and **Cage** objects manually or enable **Match high-poly and cage by name** (`_high`, `_cage`), adjust **Samples**, **Anti-aliasing** (Off, 2x, or 4x: bakes at that multiple of the resolution and shrinks it down for smooth ID, curvature, and island edges; 2x takes about 3 times as long and 4x about 13 times), and **Ray distance**, optionally **Paint cage** or **Paint skew**, and toggle **Rebake automatically**. Bakes run in the background: keep painting while the bake card and the **Bake maps** chip show progress, or click **Cancel** to stop and keep the maps as they were. Baked maps appear as thumbnails in the **Mesh maps** panel and drive **22** **Generators** (including **Mask builder**) that multiply with hand-painted masks.

## Shelf & Custom Libraries

- **Materials & Smart:** Click or drag built-in presets onto layers, right-click a material to **Paint with this material**, or save your own fill layers and folder subtrees from the layer context menu.
- **Textures & Libraries:** Import images and `.blend` materials or manage folders in **Libraries**. Suffixed PBR texture sets in library folders appear in **Materials**, `.svg` files appear as vector stencils, and right-clicking a texture lets you create a fill layer, assign it to a channel, **Use as brush alpha**, or **Use as stencil**.
- **Patterns, Masks, Generators & Filters:** Apply procedural patterns, **13** smart mask presets, **22** generators, or **67** filters by clicking or dragging onto layers.
- **Brushes, Alphas & Lighting:** Pick brush presets and stamp alphas, or switch viewport HDRIs in **Lighting**.
- **Packs:** Browse and download optional free CC0 asset packs verified by SHA-256 checksum (requires **Allow Online Access** in Blender Preferences). Note known issue **#143**: reinstalling a pack replaces its pack folder and can lose local changes or added files inside it.

## 2D View, Viewport & Texture Export

- **2D view:** Splits the viewport to dock Blender's Image Editor in Paint mode beside the 3D view, synced to the currently selected layer image or mask.
- **Viewport:** Configures the HDRI environment, rotation, strength, camera lens/orthographic toggle, color management (**View transform**, **Look**, **Exposure**, **Gamma** — exports always keep raw values), **Path traced** Cycles preview, and viewport **Post effects** (Bloom, Vignette, Color fringe, Saturation, Contrast).
- **Export textures:** Bakes from the live compiled node tree using **8** built-in templates (**Standard PBR**, **glTF**, **Unreal Engine**, **Unity HDRP**, **Unity URP**, **USD Preview Surface**, **Linear EXR**, **Spec-Gloss from Metal-Rough**) or editable custom packed templates, writing **PNG** (`8`/`16`-bit), **TGA** (`8`-bit), **TIFF** (`8`/`16`-bit), or **EXR** (`16`/`32`-bit) with configurable resolution, padding (`0`, `4`, `16`, `64` px, or `Infinite`), filename tokens, UDIM support, and **Export & send** to launch an external app. **Base Color as layered PSD** writes the active texture set's Base Color as an 8-bit PSD with one layer per layer of the stack, in stack order, keeping each layer's name, opacity, visibility, and blend mode where Photoshop has a matching mode (others fall back to Normal). The merged image inside the PSD is the same Base Color the flat export writes.
