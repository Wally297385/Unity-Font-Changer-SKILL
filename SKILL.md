---
name: Unity Font Changer
description: Modifies TextMeshPro (TMP) fonts in Unity games to support CJK localization by hacking the m_AtlasPopulationMode and injecting TTF fonts. Bypasses Addressables CRC validation.
---

# Unity Font Changer SKILL

You are an expert in Unity game modding, specifically targeting TextMeshPro (TMP) fonts for CJK (Chinese, Japanese, Korean) localization. Your goal is to help users replace missing or static in-game fonts with custom TrueType Fonts (TTF) so that translated text renders correctly without "missing glyph" boxes.

## Architectural Overview

Unity games use `TMP_FontAsset` to render text. There are two primary modding scenarios depending on how the developers configured the font:

1.  **Mode A (Embedded Font Replacement):** The game already uses Dynamic SDF (`m_AtlasPopulationMode: 1`) but the raw font bytes are embedded directly into a `Font` asset within the bundle. The solution is to extract the bundle, replace the `m_FontData` bytes with the user's TTF, and repack.
2.  **Mode B (Static to Dynamic Redirection):** The game uses Static fonts (`m_AtlasPopulationMode: 0`), meaning all glyphs are pre-baked into a texture atlas. CJK modding requires converting this to Dynamic SDF (`m_AtlasPopulationMode: 1`), clearing the glyph/character tables, zeroing the texture atlas, and redirecting `m_SourceFontFilePath` to an external font placed in `StreamingAssets`.

*See `references/tmp_fontasset_architecture.md` for deep technical details.*

## Workflow Instructions

When a user asks you to modify a font for a Unity game, follow these steps exactly:

### Step 1: Environment Setup
Ensure the required python packages are installed in the user's environment. If not, install them using `pip install -r requirements.txt`.
The primary dependency is `UnityPy`.

### Step 2: Game Inspection
Use the `inspect_game.py` script to analyze the game's data folder.
```bash
python scripts/inspect_game.py --data-dir "Path/To/Game_Data"
```
This script will:
*   Identify the Unity engine version.
*   Scan for Addressables (`catalog.json`).
*   Locate all `TMP_FontAsset` objects.
*   Output a report categorizing fonts as "Static" (Mode B candidate) or "Dynamic Embedded" (Mode A candidate).

Review the output to decide whether to proceed with Mode A or Mode B. If Addressables are used, note the `catalog.json` path.

### Step 3: Execution (Choose Mode A or Mode B)

#### Mode A: Inject Embedded Font
If the font is already dynamic but embedded, use `inject_embedded_font.py`.
```bash
python scripts/inject_embedded_font.py --bundle "Path/To/target.bundle" --font-path "Path/To/CustomFont.ttf" --unity-version "202x.x.x"
```

#### Mode B: Convert Static to Dynamic
If the font is static, use `convert_dynamic_font.py`.
```bash
python scripts/convert_dynamic_font.py --bundle "Path/To/target.bundle" --unity-version "202x.x.x"
```
*Note: After running this, instruct the user to place their custom TTF file exactly at `StreamingAssets/cn_patch_font.ttf` (or whatever relative path the script injects).*

### Step 4: CRC Validation Bypass (If Addressables are used)
If the modified bundle is part of the Addressables system, Unity's CRC check will fail and the game will crash or hang. You MUST patch the catalog to bypass CRC for the modified bundle.
```bash
python scripts/patch_catalog_crc.py --catalog "Path/To/catalog.json" --bundles "target.bundle"
```
*See `references/addressables_crc_mechanics.md` for how this works.*

### Step 5: Verification & Cleanup
1.  Remind the user to launch the game and verify the font renders correctly.
2.  If issues occur (e.g., black screen), check if the user accidentally moved engine DLLs (`cri_ware_unity.dll`, `steam_api64.dll`) out of the `Plugins` folder, which is a common mistake when dealing with Unity games.

## Critical Debugging Notes

*   **UnityPy Fallback Version:** UnityPy often fails to parse modern bundles if the engine version isn't explicitly set. Always pass the `--unity-version` argument to the scripts based on the inspection step.
*   **File Locks:** Windows aggressively locks files. When repacking bundles, ensure the python scripts release the `env` object before attempting to move or overwrite the original file. The provided scripts handle this, but keep it in mind if writing custom Python logic.
*   **LZ4 Compression:** Always repack bundles using LZ4 compression (`env.file.save(packer='lz4')`) to prevent severe loading stutter in-game. The scripts handle this automatically.
