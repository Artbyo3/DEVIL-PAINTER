# Frequently Asked Questions & Troubleshooting

This page answers common questions about installing and painting with Devil Painter (`v0.2.1`).

## Setup & Workspace

### What happens to my mesh when I click Start painting?

Devil Painter applies the chosen project **Template** and normal settings, creates one texture set per material slot (plus UDIM tiles if enabled), and unwraps meshes that lack UV coordinates using **Smart UV** or **Hard surface** mode. It assigns a compiled Devil Painter material per set, switches the 3D Viewport to **Material Preview**, and enters **Texture Paint** mode with an initial Paint layer in each set.

### Does Devil Painter alter Blender's UI permanently?

No. While the workspace is open, Devil Painter hides Blender's 3D Viewport header, tool header, toolbar, brush asset shelf, and navigation gizmo so the canvas stays uncluttered. Closing the workspace with the `×` button or <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd> restores Blender's regions. Panel positions and sizes persist across sessions, and right-clicking empty workspace space lets you choose **Reset layout**.

### Why does Devil Painter warn that two copies are installed?

If two copies are enabled at once, for example a development link to a source checkout and an installed copy from the repository or a ZIP, their operators and draw handlers conflict. Remove or disable one copy in **Edit > Preferences > Get Extensions** (or **Add-ons**) and restart Blender.

!!! warning "Known issues (v0.2.1)"
    - **#148 — Damaged settings file crash:** Devil Painter can crash if `devil_painter/library.json` in Blender's user config folder is damaged. Remove or rename that file to reset local settings.
    - **#143 — Reinstalling a pack:** Reinstalling an asset pack in the **Packs** shelf tab replaces its pack folder and can lose local changes or added files inside it.
    - **#149 — Undoing a deleted layer:** Undoing a layer deletion can restore the layer blank.

## Painting, Layers & Masks

### How does one brush stroke paint multiple channels at once?

Open the **Brush** dropdown in the tool strip and enable additional channels (such as Roughness, Metallic, Normal, or Height) alongside Base Color. Paint, Erase, Fill, Blur, Smear, and Clone strokes record into the texture set's stroke buffer and merge into each enabled channel canvas when the stroke finishes.

### How do mask generators work with hand-painted masks?

When a layer or folder has both a **Generator** and a painted mask (or **Mask effects** and a **Geometry mask**), Devil Painter combines them together. Paint white to reveal or erase/paint black to mask out specific areas on top of the procedural generator.

### Why does a generator say it needs a baked map?

Map-driven generators and effects read the mesh maps stored on the texture set (`Curvature` for Edge wear, Metal edge wear, Fiberglass edge wear, Curvature, and Cavity; `Ambient occlusion` for Ambient occlusion, Dirt, and Grime streaks; `Position` for Ground gradient and 3D/Spherical gradients; `World normal` for Top, Bottom, and Side surfaces; `Thickness` for Thickness; `UV border distance` for UV border distance; `Height` for Height; `Curvature`, `Ambient occlusion`, and `World normal` for Mask builder; and `ID` for the ID color mask effect). Click **Bake maps** in the workspace bar or the **Bake maps** chip in **Properties** to bake the required map.

### How are layers saved when I close Blender?

Saving your `.blend` file packs all Devil Painter layer images, channel canvases, baked mesh maps, and painted masks directly into the `.blend` file. You can also enable **Autosave** in the **Project** popover to save periodic packed backups in the background. (Note known issue **#149**: undoing a layer deletion can restore the layer blank.)

## 2D View & Export

### Can I paint in 2D UV space as well as 3D?

Yes. Click **2D view** in the top workspace bar to split the viewport and dock Blender's Image Editor in Paint mode beside the 3D view. It automatically displays whichever layer color image or mask is currently selected.

### What format and padding do exported textures use?

**Export textures** bakes each enabled channel or packed template output from the live material node tree into **PNG** (`8`/`16`-bit), **TGA** (`8`-bit), **TIFF** (`8`/`16`-bit), or **EXR** (`16`/`32`-bit) across selected texture sets and UDIM tiles. Resolution defaults to each set's size (`1024`, `2048`, or `4096` px) with an optional size override (`512`–`4096` px) and configurable UV island padding (`0`, `4`, `16`, `64` px, or `Infinite`). Exports always keep raw texture values regardless of viewport color management or post effects.
