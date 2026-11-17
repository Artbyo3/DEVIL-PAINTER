# User Guide

Devil Painter renders a custom, uncluttered painting workspace over Blender's 3D Viewport while keeping Blender's viewport shading and native texture paint brushes as the painting engine.

## Workspace Layout

The workspace is organized into fixed zones around the 3D Viewport stage:

- **Workspace bar (top):** Active mesh name and resolution, **Channels** selector, **View** mode selector, **Bake maps**, **2D view** toggle, **Export textures**, and **Close**.
- **Tool strip (below workspace bar):** Active tool indicator, brush color swatch (HSV + Hex popover), **Size** slider, **Opacity** slider, active **Brush alpha** slot, **Brush** popover, and quick per-channel brush swatches/values.
- **Tool dock (left):** **Paint**, **Erase**, **Fill**, **Blur**, **Smear**, **Clone**, **Undo**, and **Redo**.
- **Shelf (bottom, collapsible):** **Materials**, **Smart**, **Textures**, **Patterns**, **Masks**, **Brushes**, and **Alphas** with rendered thumbnails.
- **Right column (resizable):** Collapsible, scrollable **Layers** and **Properties** panels separated by a draggable height divider. Drag the left edge of the column to resize its width between `260 px` and `480 px`.

## Texture Sets and Channels

Each mesh object holds its own layer stack and resolution (`1024`, `2048`, or `4096` px). Use the **Channels** dropdown in the workspace bar to enable or disable any of the seven channels:

- **Base Color** (sRGB)
- **Roughness** (Non-Color)
- **Metallic** (Non-Color)
- **Normal** (Non-Color)
- **Height** (Non-Color)
- **Emission** (sRGB)
- **Opacity** (Non-Color)

Use the **View** menu to switch between the full shaded **Material**, any enabled solo channel, or any baked mesh map.

## Layers, Folders, and Masks

- **Paint layers:** Store a painted RGBA image where RGB provides Base Color and painted alpha drives coverage across every enabled channel on that layer.
- **Fill layers:** Drive each channel independently from a **Plain value**, **Texture** image, or **Procedural pattern** with **UV** or **Tri-planar** projection and adjustable **Tiling**.
- **Material layers:** Fill layers created from a shelf material remember their material definition and offer **Replace** and **Reset** actions in **Properties**.
- **Folders:** Group layers into a subtree with shared folder opacity, visibility, and folder-level masking.
- **Layer actions:** Click a row to select layer content; click the mask thumbnail to select and paint the mask; double-click a name to rename inline; right-click for context actions (duplicate, delete, mask creation, folder moves, save as material, save as smart material).

## Mesh Map Baking & Mask Generators

Open **Bake maps** in the workspace bar to bake mesh data directly with Cycles:

- **Self-mesh maps:** Ambient occlusion, Curvature, Thickness, Position, World normal, and ID.
- **High-poly bake:** Select a detailed source object under **High-poly** to bake a tangent-space **Normal** map onto the target mesh.

Once maps are baked, select any layer or folder mask and assign a **Generator** (**Edge wear**, **Cavity**, **Dirt**, **Ground gradient**, or **Thickness**). Adjust **Level**, **Contrast**, **Noise**, **Scale**, and **Invert**; generator output multiplies with any hand-painted mask strokes so you can refine edges and cavities by hand.

## Shelf & Custom Libraries

- **Materials & Smart Materials:** Click built-in presets or save your own fill layers and folder subtrees from the layer context menu.
- **Textures:** Import images into your managed library or browse any folder on disk. Suffixed PBR texture sets in a browsed folder automatically appear as ready-to-use materials in the **Materials** tab.
- **Patterns & Masks:** Apply procedural patterns (`Noise`, `Grunge`, `Cells`, `Cracks`, `Wood`, `Stripes`, `Bricks`, `Checker`) or smart mask presets with one click.
- **Brushes & Alphas:** Pick brush presets and stamp alphas, or right-click any texture in the **Textures** tab to set it as the brush alpha.

## 2D View & Texture Export

- **2D view:** Splits the viewport to dock Blender's Image Editor beside the 3D view, synced to the currently selected layer image or mask.
- **Export textures:** Bakes each enabled channel from the live compiled node tree with `16 px` UV island padding into 8-bit PNGs named with the object and channel suffix.
