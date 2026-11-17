# Reference

## Keyboard Shortcuts

| Action | Shortcut | Notes |
| :--- | :--- | :--- |
| Open or close Devil Painter | <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd> | Works when a 3D Viewport is active |
| Paint tool | <kbd>B</kbd> | Multi-channel stroke painting |
| Erase tool | <kbd>E</kbd> | Erases color and mask coverage |
| Fill tool | <kbd>G</kbd> | Flood-fills paint or mask canvas |
| Adjust brush size | <kbd>F</kbd> | Native Blender radial size control |
| Adjust brush opacity / strength | <kbd>Shift</kbd> + <kbd>F</kbd> | Native Blender radial strength control |
| Undo / Redo | <kbd>Ctrl</kbd> + <kbd>Z</kbd> / <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>Z</kbd> | Keeps the Devil Painter workspace open |

## Dock Tools

| Tool | Behavior |
| :--- | :--- |
| **Paint** | Paints base color and enabled brush channels into the stroke buffer, merging cleanly at stroke end |
| **Erase** | Removes painted pixels on the active paint layer or mask |
| **Fill** | Fills the active paint layer or mask canvas |
| **Blur** | Softens painted detail directly on the active canvas |
| **Smear** | Smudges existing pixels along the stroke |
| **Clone** | Copies image detail onto the active canvas |

## Channels & Export Maps

| Channel | Export Suffix | Color Space | Enabled by Default |
| :--- | :--- | :--- | :--- |
| **Base Color** | `BaseColor` | sRGB | Yes |
| **Roughness** | `Roughness` | Non-Color | Yes |
| **Metallic** | `Metallic` | Non-Color | Yes |
| **Normal** | `Normal` | Non-Color | Yes |
| **Height** | `Height` | Non-Color | Yes |
| **Emission** | `Emission` | sRGB | No |
| **Opacity** | `Opacity` | Non-Color | No |

## Blend Modes

Each channel slot on a layer supports independent enable, opacity, source, and blend mode:

- **Normal**
- **Multiply**
- **Screen**
- **Overlay**
- **Add**

## Procedural Patterns

Fill layer channels set to **Pattern** support **UV** or **Tri-planar** projection with **Tiling**, two values/colors, **Scale**, **Detail**, and **Contrast**:

- **Noise**, **Grunge**, **Cells**, **Cracks**, **Wood**, **Stripes**, **Bricks**, **Checker**

## Baked Mesh Maps & Mask Generators

| Mesh Map | Driven Generator(s) | Notes |
| :--- | :--- | :--- |
| **Ambient occlusion** | **Dirt** | Self-occlusion shading |
| **Curvature** | **Edge wear**, **Cavity** | Convex and concave surface detail |
| **Thickness** | **Thickness** | Inverted internal occlusion |
| **Position** | **Ground gradient** | Normalized object bounding-box coordinates |
| **World normal** | — | World-space surface normals |
| **ID** | — | Distinct color per UV island |
| **Normal** | — | Tangent-space normal baked from a chosen high-poly mesh |
