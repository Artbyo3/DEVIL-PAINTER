# Quickstart: Start > Paint > Export

This walkthrough takes a mesh from an empty scene to a multi-layer painted material and exported PNG texture maps.

## Step 1: Open Devil Painter

1. Select a mesh object in Blender's 3D Viewport.
2. Press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd>, or choose **View > Devil Painter**.

## Step 2: Start Painting

1. On the start card, choose a texture resolution: **1K**, **2K**, or **4K**.
2. Click **Start painting**.

Devil Painter automatically unwraps meshes that lack UVs, assigns a live preview material, switches the viewport to **Material Preview**, and enters **Texture Paint** mode with an initial Paint layer selected.

## Step 3: Paint on the Model

1. Choose **Paint** (<kbd>B</kbd>) or **Fill** (<kbd>G</kbd>) from the left tool dock.
2. Pick a brush color in the tool strip, adjust **Size** (<kbd>F</kbd>) and **Opacity** (<kbd>Shift</kbd> + <kbd>F</kbd>), and paint directly onto the mesh in the 3D Viewport.
3. Open **Brush** in the tool strip to configure flow, spacing, hardness, smoothing, jitter, pen pressure, and which channels each stroke paints simultaneously (such as roughness, metallic, or height alongside base color).

## Step 4: Add Fill Layers, Materials, and Masks

1. Open the bottom **Shelf** to add a **Material**, **Smart** material, **Pattern**, or **Texture** directly as a fill layer.
2. Or use the **Layers** panel header buttons to add a **Paint** layer, **Fill** layer, or **Folder**.
3. In **Properties**, add a **White mask** or **Black mask**, click the mask thumbnail in **Layers** to select it, and paint with **Paint** or **Erase** (<kbd>E</kbd>) to reveal or hide areas.

## Step 5: Bake Mesh Maps & Use Generators (Optional)

1. Click **Bake maps** in the top workspace bar.
2. Select the maps you want (**Ambient occlusion**, **Curvature**, **Thickness**, **Position**, **World normal**, **ID**, or **Normal** from a high-poly source) and click **Bake**.
3. On any layer or folder mask, choose a **Generator** (**Edge wear**, **Cavity**, **Dirt**, **Ground gradient**, or **Thickness**) or apply a preset from the **Masks** shelf tab.

## Step 6: Inspect in 2D View

Click **2D view** in the top workspace bar to dock Blender's Image Editor in Paint mode beside the 3D Viewport, displaying the active layer or mask canvas with its UV layout so you can paint in 2D or 3D seamlessly.

## Step 7: Export Textures

1. Click **Export textures** in the top workspace bar.
2. Type an output path or click **Browse** to pick a folder.
3. Click **Export** to write one padded PNG per enabled channel (`BaseColor`, `Roughness`, `Metallic`, `Normal`, `Height`, `Emission`, `Opacity`).

## Step 8: Save Your Work

Save your `.blend` file to pack all painted layer images and masks directly into the Blender file, then click the close icon (`×`) or press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd> to restore Blender's standard UI.
