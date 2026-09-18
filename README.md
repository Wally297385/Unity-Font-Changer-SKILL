# Unity Font Changer SKILL

An AI Agent Skill designed for the Google Antigravity platform to automate the process of modding Unity TextMeshPro (TMP) fonts for CJK (Chinese, Japanese, Korean) localization.

## Overview

Replacing fonts in compiled Unity games is notoriously difficult, especially for games utilizing Addressables and Static TMP FontAssets. This skill equips an AI agent with the knowledge and Python scripts necessary to autonomously:

1.  **Analyze** a Unity game's file structure and identify font architectures.
2.  **Convert** Static `TMP_FontAsset` objects to Dynamic SDF (`m_AtlasPopulationMode: 1`).
3.  **Inject** custom TrueType Fonts (TTF) into embedded `Font` assets.
4.  **Bypass** Addressables CRC validation by safely hex-editing `catalog.json` structures.

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
*   `inspect_game.py`: Scans the game directory to determine Unity version and font architecture.
*   `inject_embedded_font.py`: Replaces embedded font bytes in Addressable bundles.
*   `convert_dynamic_font.py`: Converts static pre-baked atlas fonts into dynamic runtime fonts.
*   `patch_catalog_crc.py`: Bypasses Addressable CRC hash checks.

## Documentation

For technical details on how the font manipulation and CRC bypass work, see the `references/` directory.

## License

MIT License. See `LICENSE` for details.
