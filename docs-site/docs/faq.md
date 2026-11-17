# Frequently Asked Questions & Troubleshooting

This page answers common questions about installing and painting with Devil Painter.

## Setup & Workspace

### What happens to my mesh when I click Start painting?

Devil Painter checks whether the selected mesh has UV coordinates and generates a UV map automatically if none exists. It assigns a compiled Devil Painter material to the mesh, switches the 3D Viewport to **Material Preview**, and enters **Texture Paint** mode with an initial Paint layer.

### Does Devil Painter alter Blender's UI permanently?

No. While the workspace is open, Devil Painter hides Blender's 3D Viewport header, tool header, toolbar, brush asset shelf, and navigation gizmo so the canvas stays uncluttered. Closing the workspace with the `×` button or <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd> restores Blender's regions.

### Why does Devil Painter warn that two copies are installed?

If both a repository link and an installed ZIP copy are enabled at once, their operators and draw handlers conflict. Remove or disable one copy in **Edit > Preferences > Add-ons** (or **Get Extensions**) and restart Blender.

## Painting, Layers & Masks

### How does one brush stroke paint multiple channels at once?

Open the **Brush** dropdown in the tool strip and enable additional channels (such as Roughness, Metallic, or Height) alongside Base Color. Paint and Fill strokes record into the texture set's stroke buffer and merge into each enabled channel canvas when the stroke finishes.

### How do mask generators work with hand-painted masks?

When a layer or folder has both a **Generator** (such as **Edge wear** or **Dirt**) and a painted mask, Devil Painter multiplies them together. Paint white to reveal or erase/paint black to mask out specific areas on top of the procedural generator.

### Why does a generator say it needs a baked map?

Generators read the mesh maps stored on the texture set (`Curvature` for Edge wear and Cavity, `Ambient occlusion` for Dirt, `Position` for Ground gradient, and `Thickness` for Thickness). Click **Bake maps** in the workspace bar or the **Bake maps** chip in **Properties** to bake the required map.

### How are layers saved when I close Blender?

Saving your `.blend` file packs all Devil Painter layer images, channel canvases, baked mesh maps, and painted masks directly into the `.blend` file.

## 2D View & Export

### Can I paint in 2D UV space as well as 3D?

Yes. Click **2D view** in the top workspace bar to split the viewport and dock Blender's Image Editor in Paint mode beside the 3D view. It automatically displays whichever layer color image or mask is currently selected.

### What format and padding do exported textures use?

**Export textures** bakes each enabled channel from the live material node tree as an 8-bit PNG at your texture set resolution (`1024`, `2048`, or `4096` px) with `16 px` of UV island padding. **Base Color** and **Emission** export in sRGB; **Roughness**, **Metallic**, **Normal**, **Height**, and **Opacity** export as Non-Color maps.
