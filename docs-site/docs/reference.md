# Reference

## Keyboard Shortcuts

| Action | Shortcut | Notes |
| :--- | :--- | :--- |
| Open or close Devil Painter | <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd> | Works when a 3D Viewport is active |
| Paint tool | <kbd>B</kbd> | Customizable in **Project > Shortcuts** |
| Erase tool | <kbd>E</kbd> | Customizable in **Project > Shortcuts** |
| Fill tool | <kbd>G</kbd> | Customizable in **Project > Shortcuts** |
| Smaller / larger brush | <kbd>[</kbd> / <kbd>]</kbd> | Customizable in **Project > Shortcuts** |
| Adjust brush size / opacity | <kbd>F</kbd> / <kbd>Shift</kbd> + <kbd>F</kbd> | Native Blender radial size and strength controls |
| Straight line | <kbd>Shift</kbd> + click | Paint, Erase, Blur, Smear, and Clone paint a straight line from the last painted point; with no last point it paints one dab |
| Move / scale / rotate the stencil | Right-drag / <kbd>Shift</kbd> + right-drag / <kbd>Ctrl</kbd> + right-drag | Blender's own stencil gestures on the bare viewport; the stencil card's sliders follow |
| Undo / Redo | <kbd>Ctrl</kbd> + <kbd>Z</kbd> / <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>Z</kbd> | Keeps the Devil Painter workspace open |
| Copy / paste layer(s) | <kbd>Ctrl</kbd> + <kbd>C</kbd> / <kbd>Ctrl</kbd> + <kbd>V</kbd> | While hovering a layer row |
| Apply / undo point (**Path** tool) | <kbd>Enter</kbd> / <kbd>Backspace</kbd> | Paints the ribbon or filled shape, or removes the last point |
| Cancel / close popover | <kbd>Esc</kbd> | Cancels shelf picking, text edits, or closes popovers |

**Blur**, **Smear**, **Clone**, **Toggle the 2D view**, and **Show or hide the shelf** can also be bound under **Project > Shortcuts**.

## Dock Tools

| Tool | Behavior |
| :--- | :--- |
| **Paint** | Paints base color and enabled brush channels through the stroke buffer, merging cleanly at stroke end |
| **Erase** | Erases painted pixels and enabled brush channels on the active paint layer or mask |
| **Fill** | Flood-fills the active paint layer or mask canvas across enabled brush channels |
| **Blur** | Softens painted detail across enabled channels on the active canvas |
| **Smear** | Smudges existing pixels along the stroke across enabled channels |
| **Clone** | Copies image detail onto the active canvas across enabled channels |
| **Polygon fill** | Click to fill or erase a **Triangle**, **Face**, **Mesh part**, **UV chunk**, or **Loop** |
| **Path** | Place points on the model to paint a **Ribbon** curve or **Filled** shape |
| **Undo** / **Redo** | Step backward or forward through Devil Painter history |

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
| **Ambient Occlusion** | `AmbientOcclusion` | Non-Color | No |
| **Diffuse** | `Diffuse` | sRGB | No |
| **Specular** | `Specular` | sRGB | No |
| **Glossiness** | `Glossiness` | Non-Color | No |
| **Displacement** | `Displacement` | Non-Color | No |
| **Anisotropy level** | `AnisotropyLevel` | Non-Color | No |
| **Anisotropy angle** | `AnisotropyAngle` | Non-Color | No |
| **Transmission** | `Transmission` | Non-Color | No |
| **Scattering** | `Scattering` | Non-Color | No |
| **Sheen** | `Sheen` | Non-Color | No |
| **Coat** | `Coat` | Non-Color | No |
| **IOR** | `IOR` | Non-Color | No |
| **Flow map** | `FlowMap` | Non-Color | No (export only) |
| **User 1** – **User 8** | `User1` – `User8` | Non-Color | No (export only) |

Each texture set's **Shader** decides which channels drive the viewport material:

| Channel | Principled PBR / Unlit | Spec / gloss |
| :--- | :--- | :--- |
| **Base Color**, **Roughness**, **Metallic** | Base Color, Roughness, Metallic | Not used |
| **Diffuse** | Not used | Base Color |
| **Specular** | Not used | Specular color at normal incidence (Specular Tint = value ÷ 0.04) |
| **Glossiness** | Not used | Roughness = 1 − glossiness |
| **IOR** | IOR = 1 + 2 × value (0.25 is 1.5) | Not used |
| **Anisotropy level**, **Anisotropy angle** | Anisotropic, Anisotropic Rotation (1 is a full turn) | Same |
| **Transmission**, **Scattering**, **Sheen**, **Coat** | Transmission, Subsurface, Sheen, and Coat weights | Same |
| **Displacement** | Material displacement around a 0.5 midlevel | Same |

Every channel exports its own painted values whichever shader is chosen.

Built-in export templates are **Standard PBR**, **glTF**, **Unreal Engine**, **Unity HDRP**, **Unity URP**, **USD Preview Surface**, **Linear EXR**, and **Spec-Gloss from Metal-Rough** (or copy any template to customize packed outputs). **Spec-Gloss from Metal-Rough** converts Base Color, Metallic, and Roughness at export time: Diffuse = Base Color × (1 − Metallic), Specular = 0.04 × (1 − Metallic) + Base Color × Metallic, Glossiness = 1 − Roughness. The same converted sources (**Converted Diffuse**, **Converted Specular**, **Converted Glossiness**) are available in custom templates; painted Diffuse, Specular, and Glossiness channels export unchanged. Supported formats are **PNG** (`8`/`16`-bit), **TGA** (`8`-bit), **TIFF** (`8`/`16`-bit), and **EXR** (`16`/`32`-bit). Filename tokens: `{mesh}`, `{set}`, `{output}`, `{udim}`, `{material}`, `{resolution}`.

## Blend Modes

Each channel slot on a layer supports independent enable, opacity, source, and blend mode:

- **Normal**, **Darken**, **Multiply**, **Color burn**, **Lighten**, **Screen**, **Color dodge**, **Linear dodge (Add)**, **Overlay**, **Soft light**, **Linear light**, **Difference**, **Exclusion**, **Subtract**, **Divide**, **Hue**, **Saturation**, **Color**, **Value**, **Normal map detail**

Folders also support **Passthrough** (in addition to layer blend modes except Normal map detail). Mask effects support **Multiply**, **Add**, **Subtract**, **Replace**, **Darken**, **Lighten**, and **Difference**.

## Procedural Patterns

Fill layer channels set to **Pattern** support **UV**, **Tri-planar**, **Planar**, **Spherical**, and **Cylindrical** projection with **Tiling**, two values/colors, **Scale**, **Detail**, and **Contrast**:

- **Noise**, **Grunge**, **Cells**, **Cracks**, **Wood**, **Stripes**, **Bricks**, **Checker**

## Baked Mesh Maps & Mask Generators

| Mesh Map | Driven Generator(s) / Effect | Notes |
| :--- | :--- | :--- |
| **Ambient occlusion** | **Ambient occlusion**, **Dirt**, **Grime streaks**, **Mask builder** | Self-occlusion shading |
| **Curvature** | **Curvature**, **Edge wear**, **Metal edge wear**, **Fiberglass edge wear**, **Cavity**, **Mask builder** | Convex and concave surface detail |
| **Thickness** | **Thickness** | Inverted internal occlusion |
| **Position** | **Ground gradient**, **3D gradient X**, **3D gradient Y**, **3D gradient Z**, **3D spherical gradient** | Normalized object bounding-box coordinates |
| **World normal** | **Top surfaces**, **Bottom surfaces**, **Side surfaces**, **Mask builder** | World-space surface normals |
| **ID** | **ID color** mask effect | Colored by UV islands, Materials, Objects, or Vertex colors |
| **Normal** | — | Tangent-space normal from high-poly, or rounded edges from the mesh itself |
| **Height** | **Height** | Height difference baked from a high-poly mesh |
| **UV border distance** | **UV border distance** | Distance from UV island seams |

**Noise** and **Scratches** generators work procedurally without baked maps.
