# Quickstart: Start > Paint > Export

This walkthrough takes a mesh from an empty scene to a multi-layer painted material and exported texture maps.

## Step 1: Open Devil Painter

1. Select a mesh object in Blender's 3D Viewport.
2. Press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd>, or choose **View > Devil Painter**.

## Step 2: Start Painting

1. On the **New Devil Painter project** start card, pick a **Template** (such as **PBR Metal Rough**, **Unreal Engine**, or **Hand-painted Unlit**), **Normal map** format (**OpenGL** / **DirectX**) and tangent mode, and a **1K**, **2K**, or **4K** resolution per material-slot texture set.
2. If your mesh has no UVs, choose **Smart UV** or **Hard surface** unwrapping. If UDIM tiles are detected, toggle **Use UDIM tiles from the UV layout** as needed.
3. Click **Start painting**.

Devil Painter creates one texture set per material slot with an initial Paint layer, assigns live preview materials, switches the viewport to **Material Preview**, and enters **Texture Paint** mode.

## Step 3: Paint on the Model

1. Choose **Paint** (<kbd>B</kbd>), **Fill** (<kbd>G</kbd>), **Erase** (<kbd>E</kbd>), **Blur**, **Smear**, **Clone**, **Polygon fill**, or **Path** from the left tool dock.
2. Pick a brush color in the tool strip, adjust **Size** (<kbd>F</kbd> or <kbd>[</kbd> / <kbd>]</kbd>) and **Opacity** (<kbd>Shift</kbd> + <kbd>F</kbd>), and paint directly onto the mesh in the 3D Viewport.
3. Open **Brush** in the tool strip to configure flow, spacing, hardness, **Lazy mouse**, jitter, angle, stroke method, dynamics, pen pressure (size, opacity, flow, hardness, and angle each have their own toggle), and which channels each stroke paints and erases simultaneously. Use **Symmetry** for mirror or radial strokes, **Stencil** to paint through or project images/text/SVGs, and **Quick mask** for temporary masks.

## Step 4: Add Fill Layers, Materials, and Masks

1. Open the bottom **Shelf** to click or drag a **Material**, **Smart** material, **Texture**, **Pattern**, **Mask**, **Generator**, or **Filter** onto the layer stack.
2. Or use the **Layers** panel header buttons to add a **Folder**, **Fill** layer, or **Paint** layer.
3. In **Properties**, add a **White mask** or **Black mask**, a **Geometry mask**, or **Mask** and **Content** effects (**Paint**, **Fill**, **Levels**, **Filter**, **Compare mask**, **Anchor**, **ID color**). Click a mask thumbnail in **Layers** to select and paint it.

## Step 5: Bake Mesh Maps & Use Generators (Optional)

1. Click **Bake maps** in the top workspace bar.
2. Select from the nine mesh maps (**Ambient occlusion**, **Curvature**, **Thickness**, **Position**, **World normal**, **ID**, **Normal**, **Height** from a high-poly mesh, and **UV border distance**), set high-poly/cage options if needed, and click **Bake**.
3. On any layer or folder, choose one of the **22** **Generators** (such as **Edge wear**, **Cavity**, **Dirt**, **Ground gradient**, **Thickness**, or **Mask builder**) or apply a preset from the **Masks** shelf tab.

## Step 6: Inspect in 2D View

Click **2D view** in the top workspace bar to dock Blender's Image Editor in Paint mode beside the 3D Viewport, displaying the active layer or mask canvas with its UV layout so you can paint in 2D or 3D seamlessly.

## Step 7: Export Textures

1. Click **Export textures** in the top workspace bar.
2. Pick an **Export template** (**Standard PBR**, **glTF**, **Unreal Engine**, **Unity HDRP**, **Unity URP**, **USD Preview Surface**, **Linear EXR**, **Spec-Gloss from Metal-Rough**, or a custom copy), choose which texture sets to include, and adjust **Depth**, **Size**, **Padding**, and filename **Pattern** tokens.
3. Type an output folder or click **Browse**, then click **Export** (or **Export & send** to open the files in another app).

## Step 8: Save Your Work

Save your `.blend` file to pack all painted layer images, channel canvases, baked maps, and masks directly into the Blender file (or enable **Autosave** under **Project** for background packed backups). Click the close icon (`×`) or press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd> to restore Blender's standard UI.
