# Unity Font Changer SKILL

An AI Agent Skill designed for the Google Antigravity platform to automate the process of modding Unity TextMeshPro (TMP) fonts for CJK (Chinese, Japanese, Korean) localization.

## Overview

Replacing fonts in compiled Unity games is notoriously difficult, especially for games utilizing Addressables and Static TMP FontAssets. This skill equips an AI agent with the knowledge and Python scripts necessary to autonomously:

1.  **Analyze** a Unity game's file structure and identify font architectures.
2.  **Convert** Static `TMP_FontAsset` objects to Dynamic SDF (`m_AtlasPopulationMode: 1`).
3.  **Inject** custom TrueType Fonts (TTF) into embedded `Font` assets.
4.  **Re-bake** Static `TMP_FontAsset` SDF atlases with a new TTF/OTF (Mode C) for games whose own renderer reads the glyph tables, or whose TMP version cannot load external fonts.
5.  **Check** a replacement font's coverage against the game's text and font tables, and **preview** the result in the game's text style before installing.
6.  **Bypass** Addressables CRC validation in `catalog.json`, and read/zero CRCs in binary `catalog.bin` (Addressables 1.21+).

## Installation

This repository is designed to be used as an Antigravity Agent Skill. 

1. Clone this repository into your global agent skills directory:
   ```bash
   git clone https://github.com/Wally297385/Unity-Font-Changer-SKILL.git ~/.gemini/config/skills/unity-font-changer
   ```
2. The skill will now be available to your Antigravity agent. Simply ask the agent to "Change the font for [Game Name]".

## Usage

You do not need to run these scripts manually. The AI agent will read `SKILL.md` and execute the Python scripts inside `scripts/` as needed when you request a font modification. 

### Included Scripts
*   `inspect_game.py`: Scans the game directory to determine Unity version, font architecture and text stack, and recommends a mode.
*   `inject_embedded_font.py`: Mode A - replaces embedded font bytes in Addressable bundles.
*   `convert_dynamic_font.py`: Mode B - converts static pre-baked atlas fonts into dynamic runtime fonts.
*   `bake_static_atlas.py`: Mode C - re-bakes a static SDF atlas, glyph table and character table with a new font.
*   `check_font_coverage.py`: Reports characters a replacement font is missing, against the font asset and the game's text.
*   `preview_atlas.py`: Renders sample text from original and patched bundles, approximating the in-game SDF style.
*   `patch_catalog_crc.py`: Bypasses Addressable CRC checks in `catalog.json`.
*   `catalog_bin_crc.py`: Reads, and optionally zeroes, bundle CRCs in a binary `catalog.bin`.

### Tested Games
*   **Tales of Graces f Remastered** (Unity 2022.3.26f1, Addressables 1.21.20 `catalog.bin`, native text renderer): Traditional Chinese font replaced with Mode C. See `references/static_atlas_rebake.md`.

## Documentation

For technical details on how the font manipulation and CRC bypass work, see the `references/` directory:

*   `tmp_fontasset_architecture.md` - TMP_FontAsset internals, Mode A/B.
*   `static_atlas_rebake.md` - Mode C: when it is required, how the SDF re-bake works, case study and tuning notes.
*   `addressables_crc_mechanics.md` - CRC bypass for `catalog.json` and `catalog.bin`.

## License

MIT License. See `LICENSE` for details.
