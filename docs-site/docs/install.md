# Install Devil Painter

## Before You Install

You need **Blender 5.2 or later**; no external Python packages or external tools are required. The current release is **v0.4.0** (`2026-11-20`), licensed under **GPL-3.0-or-later**.

Everything needed for painting, baking, and exporting works offline. If you want to browse or download optional free asset packs from the **Packs** shelf tab, also enable **Allow Online Access** in **Edit > Preferences > System**.

## Install from GitHub Release ZIP

1. Download `devil_painter-0.4.0.zip` (or the latest `devil_painter-*.zip`) from the [GitHub releases page](https://github.com/Artbyo3/DEVIL-PAINTER/releases/download/v0.4.0/devil_painter-0.4.0.zip?repository=https%3A%2F%2Fartbyo3.github.io%2FDEVIL-PAINTER%2Frepo%2Findex.json&blender_version_min=5.2.0).
2. Open Blender and choose **Edit > Preferences**.
3. Open **Get Extensions** (or **Add-ons**).
4. Open the top-right menu (`⌄`) and choose **Install from Disk...**.
5. Select the downloaded ZIP file and confirm.

<a id="build-and-install-from-source"></a>
## Build and Install from Source

If you want to package the extension directly from the repository:

1. Clone the repository:
   ```bash
   git clone https://github.com/Artbyo3/DEVIL-PAINTER.git
   cd DEVIL-PAINTER
   ```
2. Build the extension archive:
   ```bash
   python tools/build.py
   ```
3. In Blender, choose **Edit > Preferences > Get Extensions** (or **Add-ons**) **> Install from Disk...** and select `dist/devil_painter-0.4.0.zip`.

## Enable Devil Painter

Find **Devil Painter** in the add-on list and check its box to enable it.

!!! warning "Only keep one copy enabled"
    If more than one copy of Devil Painter is installed (for example, both a development link and a ZIP install), disable or remove the duplicate copy under **Preferences > Get Extensions** or **Preferences > Add-ons** and restart Blender.

## Open the Workspace

From any 3D Viewport, use one of these options:

- Press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd>.
- Press <kbd>F3</kbd>, search for **Devil Painter**, and press <kbd>Enter</kbd>.
- Choose **View > Devil Painter** from the 3D Viewport header menu.

## Upgrade or Reinstall

1. Uncheck the older **Devil Painter** entry in **Edit > Preferences > Get Extensions** or **Add-ons** (or remove it).
2. Restart Blender.
3. Install the newer `devil_painter-*.zip` using **Install from Disk...** and enable it again.

## Fix Common Install Problems

- **Devil Painter is missing from the add-on list:** Confirm the ZIP was built with `tools/build.py` (or downloaded from Releases) and check that Blender is version 5.2 or later.
- **The checkbox stays off or warns about two copies:** Remove any older copy of Devil Painter in Preferences and restart Blender before enabling the new build.
- **The workspace does not open:** Click inside a 3D Viewport so it is the active area, then press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>P</kbd> or choose **View > Devil Painter**.
- **Devil Painter crashes when reading settings (#148):** If the `library.json` settings file in Blender's user config folder (`devil_painter/library.json`) is damaged, Devil Painter can crash on load; remove or rename that file to reset local settings.
