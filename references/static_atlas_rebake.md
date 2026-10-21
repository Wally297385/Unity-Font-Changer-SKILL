# Mode C: Static Atlas Re-bake

Mode A and Mode B both end with a **Dynamic** `TMP_FontAsset`: the glyph table starts empty and
TextMeshPro fills the atlas at runtime. That only works when TMP itself draws the text and can
reach the font data. Mode C keeps the asset **Static** and replaces what is baked into it: the
atlas texture, the glyph table and the character table are regenerated offline from the new
TTF/OTF with the same layout parameters as the original.

## When Mode C is required

| Symptom / finding | Why A/B fail |
|---|---|
| Game code (`Assembly-CSharp`) calls `TMP_FontAsset.characterTable` / `glyphTable` / `atlasTexture` itself | A custom or native renderer copies the glyph data **once** at startup. A Dynamic asset has an empty table at that moment, so nothing renders, and nothing ever calls `TryAddCharacters`. |
| `Unity.TextMeshPro.dll` has no `m_SourceFontFilePath` (TMP 3.0.x, Unity 2020–2022 default) | Mode B's external font path does not exist in this TMP version; a Dynamic asset without a `Font` object cannot load a face. |
| Text uses a fixed shader (e.g. a hard-coded `_GradientScale`) | The new atlas must keep the same padding/SDF spread, which a re-bake controls exactly. |

`inspect_game.py` checks all three and prints the recommendation.

## Case study: Tales of Graces f Remastered (Unity 2022.3.26f1)

* Addressables 1.21.20 with a **binary `catalog.bin`**; all fonts in `togf_font_assets_all.bundle`.
* Text is drawn by the native Noble engine. `Noble.FontAssetManager` loads one root
  `TMP_FontAsset` per language (Addressables key `7000009` = `NobleFont_cht`), walks
  `fallbackFontAssetTable`, and copies every fallback's `characterTable` + `glyphTable` into a
  dictionary keyed by UTF-8 code. The native side then draws quads from `atlasTexture`.
* The root assets are empty (8×8 atlas, 0 glyphs); the real glyphs live in their fallbacks.
  `NobleFont_cht` → `[0] FOT-RodinBokutohPro-M SDF` (Japanese), `[1] Frutiger` (Latin),
  `[2] DFT_L5 SDF` (Traditional Chinese, 3650 glyphs). For Traditional Chinese the game looks in
  fallback `[2]` first, then `[0]`. Re-baking only `DFT_L5 SDF` changed all Chinese text.
* Scale and baseline for every glyph come from the **region asset's** `m_FaceInfo`, so the
  original face info is kept and the new glyphs are aligned to it instead.
* Per-language look is tuned in a separate ScriptableObject (`NobleFontGlobalData_tc`:
  `_FaceDilate 0.3`, `_OutlineWidth 0.2`, `_FontSizeOffset +8`). These were tuned for the
  original squat 隸書 face; a regular-proportion font looks larger and bolder in game than in a
  plain preview. Choose a lighter weight (Medium instead of Bold) or edit these values.
* The bundle's CRC in `catalog.bin` was already `0`, so no catalog patch was needed.

## How the re-bake works (`bake_static_atlas.py`)

1. **Read the layout** from the original asset: atlas size, `m_AtlasPadding` (p), point size,
   render mode. TMP's SDF material uses `_GradientScale = p + 1`, and the atlas alpha encodes
   `alpha = 0.5 + d / (2 × (p + 1))` with `d` the signed distance in texels (measured on the
   original atlas: ~18.2 alpha steps per texel for p = 6). The new atlas uses the same spread, so
   the game's shader keeps working unchanged.
2. **Character set** = the asset's existing character table (plus `--extra-chars`). Keeping the
   table guarantees every character the game could ask for still exists.
3. **Render** each glyph with Pillow/FreeType at 8× supersampling, threshold, compute an exact
   Euclidean distance transform (SciPy) inside and outside, downsample to texels, encode as above.
   Each glyph gets `p + 1` texels of SDF border.
4. **Metrics**: the glyph's outline bounds (at `pointSize × scale`) are snapped outward to whole
   pixels; that box becomes both `m_GlyphRect` size and `m_Metrics` (width/height/bearings), so
   the quad maps 1:1 onto the atlas region. Advance = font advance × scale.
5. **Vertical alignment**: the new font's ideographs are shifted (`dy`) so their average centre
   matches the old glyphs' average centre (`--dy` overrides). Fonts differ a lot here (the old face
   was centred 3–4 px lower than most modern fonts at 48 pt).
6. **Missing characters** keep the old glyph: its SDF region is copied from the old atlas with its
   original metrics, so nothing turns into tofu.
7. **Pack** with a shelf packer into an atlas of the original size, rewrite `m_GlyphTable`,
   `m_CharacterTable`, `m_UsedGlyphRects` (`m_FreeGlyphRects` cleared), the face family/style
   names, and the `Texture2D` (inline data; `m_StreamData` cleared by UnityPy), then save with LZ4.

## Workflow

```bash
# 1. which asset serves the language, and is Mode C needed?
python scripts/inspect_game.py --game-dir "Path/To/Game"

# 2. coverage of the new font (text files may be binary containers holding UTF-8)
python scripts/check_font_coverage.py --bundle ".../togf_font_assets_all.bundle" --asset "DFT_L5 SDF" \
    --font MyFont.ttf --text ".../Message/tc/*.bin" --chain "DFT_L5 SDF" "FOT-RodinBokutohPro-M SDF"

# 3. bake to a separate file first and preview it against the original
python scripts/bake_static_atlas.py --bundle ".../togf_font_assets_all.bundle" --asset "DFT_L5 SDF" \
    --font MyFont.ttf --out out/togf_font_assets_all.bundle
python scripts/preview_atlas.py ".../togf_font_assets_all.bundle" out/togf_font_assets_all.bundle \
    --asset "DFT_L5 SDF" --out out/preview.png --dilate 0.3 --outline 0.2

# 4. install: copy over the game bundle (keep the original!), or bake in place (makes .bak)
python scripts/bake_static_atlas.py --bundle ".../togf_font_assets_all.bundle" --asset "DFT_L5 SDF" --font MyFont.ttf

# 5. CRC: binary catalogs
python scripts/catalog_bin_crc.py --catalog ".../aa/catalog.bin" --bundles ".../togf_font_assets_all.bundle"
```

## Tuning notes

* **Too big / crowded**: `--scale 0.9` shrinks glyphs and advances. Prefer lowering the game's
  own per-language size offset if it has one, so the atlas keeps full resolution.
* **Too bold in game**: the game's material usually adds `_FaceDilate` and an outline. Preview
  with the game's values (`--dilate`, `--outline`) and pick a lighter weight.
* **Capacity**: at 48 pt with padding 6, a 4096² atlas holds ~4,500 CJK glyphs. If it overflows,
  lower `--scale` or the character set.
* **Fallback-only symbols** (here `™∀♪・`, served by the Japanese asset) can be moved into the
  re-baked asset with `--extra-chars` when the new font has them.
* Text harvested from binary containers contains noise (random 2-byte UTF-8 sequences); compare
  only against the fonts in the language's fallback chain (`--chain`).
* Steam "verify integrity of game files" or a game update restores the original bundle.
