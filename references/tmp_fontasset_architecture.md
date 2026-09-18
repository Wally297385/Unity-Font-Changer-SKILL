# Unity TextMeshPro (TMP) FontAsset Architecture

Unity's TextMeshPro (TMP) relies heavily on `TMP_FontAsset` objects to manage fonts. Understanding the internal structure of this object is crucial for modifying in-game typography.

## Core Properties

A `TMP_FontAsset` (class ID 114, MonoBehaviour) is essentially a wrapper around font data and a rendered atlas.

### 1. `m_AtlasPopulationMode`
This is the most critical property determining how the font behaves at runtime.
*   **Mode 0 (Static):** The font atlas (`m_AtlasTexture`) is pre-rendered in the editor. Only the characters baked into the texture can be displayed. CJK games using Mode 0 are extremely difficult to modify via traditional means because adding new characters requires recalculating UVs, packing the texture, and updating the glyph table.
*   **Mode 1 (Dynamic SDF):** The font relies on raw TTF/OTF font bytes to generate the atlas texture *at runtime* as new characters are requested by the UI. This is the holy grail for CJK localization.

### 2. `m_FontData` and `m_SourceFontFilePath` (Source of Truth)
For Dynamic SDF to work, the engine must know where to find the raw `.ttf` or `.otf` data. Unity has two ways of handling this:
*   **Embedded (`m_FontData`):** The actual font file bytes (e.g., `ARFangXinShu-Heavy.ttf`) are embedded directly into a `Font` asset (class ID 128) which is linked here. This is common in some Addressable bundles.
*   **External Redirection (`m_SourceFontFilePath`):** The engine looks for an external file path. Usually, this path is relative to the project directory, but in built games, if redirected correctly, it can point to the `StreamingAssets` directory or an absolute path (though OS-dependent).

### 3. `m_AtlasTexture`
The texture holding the rendered glyphs.
*   In **Static** mode, this is a fully packed texture containing all glyphs.
*   In **Dynamic** mode, this is an empty Alpha8 or RGBA32 texture (often 1024x1024 or 2048x2048). The engine dynamically draws into this texture as new characters appear on screen.

### 4. `m_GlyphTable` and `m_CharacterTable`
*   In **Static** mode, these tables contain thousands of entries mapping Unicode characters to their specific UV coordinates in the `m_AtlasTexture`.
*   In **Dynamic** mode, these tables are often empty (or contain only a few basic ASCII characters) because they are populated dynamically at runtime.

---

## Modding Strategies

Based on the architecture above, there are two primary strategies for modifying fonts in Unity games.

### Strategy A: Embedded Font Replacement (For existing Mode 1)
If a game is *already* using Dynamic SDF (`m_AtlasPopulationMode: 1`) but the font data is embedded (`m_FontData`), you can simply overwrite the embedded bytes.
1.  Identify the bundle containing the `Font` asset (ID 128) linked to the `TMP_FontAsset`.
2.  Extract the bundle using UnityPy.
3.  Replace the raw bytes in the `Font` asset's `m_FontData` array with your custom TTF bytes.
4.  Repack the bundle using LZ4 compression (`env.file.save(packer='lz4')`).

### Strategy B: Static to Dynamic Redirection (For Mode 0)
If a game uses Static fonts (`m_AtlasPopulationMode: 0`), you must "upgrade" it to Dynamic SDF and point it to an external font file.
1.  Change `m_AtlasPopulationMode` from 0 to 1.
2.  Set `m_SourceFontFilePath` to point to a reliable location, such as `StreamingAssets/custom_font.ttf` (relative to the game executable's `_Data` folder).
3.  Clear the `m_GlyphTable` and `m_CharacterTable` (set to empty arrays/lists) to force the engine to generate everything from scratch.
4.  Zero out the `m_AtlasTexture`. Find the `Texture2D` asset, set its dimensions to a standard size (e.g., 2048x2048), set its format to `Alpha8` (format 1), and provide empty byte data for the image.
5.  Repack the bundle and ensure the custom TTF file is placed in the designated path (e.g., the `StreamingAssets` folder).
