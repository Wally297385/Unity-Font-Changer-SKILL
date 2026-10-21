---
name: Unity Font Changer
description: Modifies TextMeshPro (TMP) fonts in Unity games to support CJK localization - injects TTF data into embedded fonts, converts static fonts to dynamic, or re-bakes static SDF atlases with a new font for games whose own renderer reads the glyph tables. Handles Addressables CRC validation for catalog.json and catalog.bin.
---

# Unity Font Changer SKILL

You are an expert in Unity game modding, specifically targeting TextMeshPro (TMP) fonts for CJK (Chinese, Japanese, Korean) localization. Your goal is to help users replace missing or unwanted in-game fonts with custom TrueType/OpenType fonts so that text renders correctly without "missing glyph" boxes.

## Architectural Overview

Unity games use `TMP_FontAsset` to render text. There are three modding scenarios depending on how the developers configured the font and who draws the text:

1.  **Mode A (Embedded Font Replacement):** The game already uses Dynamic SDF (`m_AtlasPopulationMode: 1`) and the raw font bytes are embedded in a `Font` asset within the bundle. Replace the `m_FontData` bytes with the user's TTF and repack.
2.  **Mode B (Static to Dynamic Redirection):** The game uses Static fonts (`m_AtlasPopulationMode: 0`). Convert to Dynamic SDF, clear the glyph/character tables, zero the atlas, and redirect `m_SourceFontFilePath` to an external font in `StreamingAssets`. Requires a TMP version that has `m_SourceFontFilePath` (TMP 3.2+/4.x) and text drawn by TMP itself.
3.  **Mode C (Static Atlas Re-bake):** Keep the asset Static and regenerate its SDF atlas, glyph table and character table offline from the new font, with the same atlas size, point size, padding and SDF spread. Required when the game's own (often native) renderer copies the glyph tables at startup, or when TMP is 3.0.x — in both cases a Dynamic asset renders blank text.

*See `references/tmp_fontasset_architecture.md` for TMP internals and `references/static_atlas_rebake.md` for Mode C details and a full case study.*

## Workflow Instructions

When a user asks you to modify a font for a Unity game, follow these steps:

### Step 1: Environment Setup
Ensure the required python packages are installed: `pip install -r requirements.txt` (UnityPy, fonttools, lz4, numpy, scipy, Pillow).

### Step 2: Game Inspection
```bash
python scripts/inspect_game.py --game-dir "Path/To/Game"
```
This script will:
*   Identify the Unity engine version.
*   Scan Addressables (`catalog.json`, or `catalog.bin` for Addressables 1.21+ by bundle name).
*   List every `TMP_FontAsset` (mode, baked glyphs, atlas size, padding, fallback count) and embedded `Font`.
*   Check the text stack: whether TMP can load an external font file, and whether `Assembly-CSharp` reads `characterTable`/`glyphTable` itself.
*   Print a Mode A / B / C recommendation.

Then identify **which asset actually serves the user's language**. Language "root" assets are often empty (8×8 atlas, 0 glyphs) and only list fallbacks; follow the fallback list and, on Mono builds, decompile `Assembly-CSharp.dll` (`ilspycmd`) to see how the game picks the root and walks the fallbacks.

### Step 3: Coverage Check (before Mode C, recommended for all modes)
```bash
python scripts/check_font_coverage.py --bundle "Path/To/fonts.bundle" --asset "<TMP asset name>" --font "Path/To/CustomFont.ttf" --text "Path/To/game/text/*.bin"
```
Reports characters the new font is missing (or draws empty), split into "used by the game text" and "only in the asset's table". Tell the user what is missing and confirm how to handle it before baking (Mode C keeps the original glyph for missing characters by default).

### Step 4: Execution (Choose Mode A, B or C)

#### Mode A: Inject Embedded Font
```bash
python scripts/inject_embedded_font.py --bundle "Path/To/target.bundle" --font "Path/To/CustomFont.ttf" --unity-version "202x.x.x"
```

#### Mode B: Convert Static to Dynamic
```bash
python scripts/convert_dynamic_font.py --bundle "Path/To/target.bundle" --font-relative-path "StreamingAssets/cn_patch_font.ttf" --unity-version "202x.x.x"
```
*Then instruct the user to place their TTF at exactly the path passed in `--font-relative-path`.*

#### Mode C: Re-bake Static Atlas
Bake to a separate file first, preview against the original, then install:
```bash
python scripts/bake_static_atlas.py --bundle "Path/To/fonts.bundle" --asset "<TMP asset name>" --font "Path/To/CustomFont.ttf" --out out/fonts.bundle
python scripts/preview_atlas.py "Path/To/fonts.bundle" out/fonts.bundle --asset "<TMP asset name>" --out out/preview.png --dilate <game _FaceDilate> --outline <game _OutlineWidth>
```
*   Without `--out` the script patches in place and keeps `<bundle>.bak` (always re-baked from the `.bak`).
*   `--scale 0.9` makes glyphs smaller; `--extra-chars` adds characters (e.g. symbols currently served by another fallback asset).
*   Preview with the game's material values: games often add face dilation and outlines, so a Bold font that looks fine in a plain preview can look far too heavy in game.

### Step 5: CRC Validation Bypass (If Addressables are used)
If the modified bundle is checked by CRC, the game will fail to load it. Check first; many games ship local bundles with CRC `0` (no check).
```bash
# catalog.json
python scripts/patch_catalog_crc.py --catalog "Path/To/catalog.json" --bundles "target.bundle"
# catalog.bin (Addressables 1.21+): reads the CRC; add --patch to zero it
python scripts/catalog_bin_crc.py --catalog "Path/To/catalog.bin" --bundles "Path/To/target.bundle"
```
*See `references/addressables_crc_mechanics.md` for how this works.*

### Step 6: Verification & Cleanup
1.  Reload the patched bundle and confirm only the intended assets changed and no characters were lost (the scripts verify their own output; for Mode C also compare character tables before/after).
2.  Have the user launch the game and check real screens (dialogue, menus, item descriptions). Ask for screenshots when something looks off.
3.  If issues occur (e.g., black screen), check whether engine DLLs (`cri_ware_unity.dll`, `steam_api64.dll`) were accidentally moved out of the `Plugins` folder.
4.  Keep the original bundle backed up; Steam "verify integrity" or a game update restores the original.

## Critical Debugging Notes

*   **UnityPy Fallback Version:** UnityPy often fails to parse modern bundles if the engine version isn't explicitly set. Always pass `--unity-version` based on the inspection step.
*   **File Locks:** Windows aggressively locks files. Release the UnityPy `env` before moving or overwriting the original file. The provided scripts handle this.
*   **LZ4 Compression:** Always repack bundles with LZ4 (`env.file.save(packer='lz4')`) to avoid loading stutter. The scripts handle this.
*   **Blank text after Mode A/B:** the game probably reads the font tables itself or its TMP cannot load external fonts — switch to Mode C.
*   **Per-language tuning objects:** some games keep size offset / dilate / outline per language in a ScriptableObject separate from the font. Values tuned for the original font can make a new font look too big or too bold; adjust those or pick a lighter weight.
*   **Text in binary containers:** game text is often UTF-8 inside custom archives; harvesting characters from them yields noise, so compare only against the language's fallback chain (`check_font_coverage.py --chain`).
