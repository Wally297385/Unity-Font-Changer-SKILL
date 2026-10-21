"""Mode C: re-bake a static TMP_FontAsset atlas with a new TTF/OTF.

Use this when the game reads the TMP_FontAsset's glyph/character tables itself (custom/native
text renderer) or when its TMP version cannot load an external font at runtime, so switching the
asset to Dynamic (Mode A/B) leaves the text blank. The script renders the asset's character set
with the new font into a fresh SDF atlas that keeps the original layout parameters (atlas size,
point size, padding, SDF spread) and writes the glyph table, character table and texture back.

Characters the new font lacks keep their original glyph, copied from the old atlas.
"""
import argparse, gc, math, os, shutil

import numpy as np
import UnityPy
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt

SUPERSAMPLE = 8   # hi-res factor used before computing the distance field
CJK_SAMPLE = '口國田日目四回圖的是不了人一中大我你他這那會說資料保存地上'
LATIN_SAMPLE = 'HIEOXhnoxz'


def load_font_asset(env, name):
    fa_obj = fa = None
    for obj in env.objects:
        if obj.type.name == 'MonoBehaviour':
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            if tree.get('m_Name') == name and 'm_GlyphTable' in tree:
                fa_obj, fa = obj, tree
    if fa_obj is None:
        raise SystemExit(f'[Error] TMP_FontAsset "{name}" not found in bundle')
    if fa.get('m_AtlasPopulationMode', 0) != 0:
        print('[Warning] Asset is not Static (m_AtlasPopulationMode != 0); Mode A/B may fit better.')
    tex_pid = fa['m_AtlasTextures'][0]['m_PathID']
    tex_obj = next(obj for obj in env.objects if obj.path_id == tex_pid)
    return fa_obj, fa, tex_obj


def glyph_center_offset(fa, font, k, sample):
    """Vertical shift (px) that puts the new glyphs' centers where the old ones were."""
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    glyphs = {g['m_Index']: g for g in fa['m_GlyphTable']}
    chars = {c['m_Unicode']: glyphs.get(c['m_GlyphIndex']) for c in fa['m_CharacterTable']}
    for candidates in ([sample] if sample else [CJK_SAMPLE, LATIN_SAMPLE]):
        old, new = [], []
        for ch in candidates:
            g = chars.get(ord(ch))
            if g and g['m_Metrics']['m_Height'] > 0 and ord(ch) in cmap:
                bp = BoundsPen(gs); gs[cmap[ord(ch)]].draw(bp)
                if bp.bounds:
                    m = g['m_Metrics']
                    old.append(m['m_HorizontalBearingY'] - m['m_Height'] / 2)
                    new.append((bp.bounds[1] + bp.bounds[3]) / 2 * k)
        if len(old) >= 3:
            return float(np.mean(old) - np.mean(new))
    print('[Warning] Not enough shared sample glyphs to auto-align; using dy=0')
    return 0.0


def render_sdf(pil_font, ch, x0, y1, w, h, dy, pad, spread):
    """Return a (h+2*pad) x (w+2*pad) uint8 SDF tile, row 0 = top."""
    S = SUPERSAMPLE
    hi = Image.new('L', ((w + 2 * pad) * S, (h + 2 * pad) * S), 0)
    ImageDraw.Draw(hi).text(((pad - x0) * S, (pad + y1 - dy) * S), ch, font=pil_font, fill=255, anchor='ls')
    mask = np.asarray(hi) > 127
    if not mask.any():
        return np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    inside = distance_transform_edt(mask)
    outside = distance_transform_edt(~mask)
    sd = np.where(mask, inside - 0.5, -(outside - 0.5)) / S
    sd = sd.reshape(h + 2 * pad, S, w + 2 * pad, S).mean(axis=(1, 3))
    return np.clip(np.rint(127.5 + sd * 255.0 / (2 * spread)), 0, 255).astype(np.uint8)


class ShelfPacker:
    def __init__(self, width, height):
        self.width, self.height, self.x, self.y, self.row_h = width, height, 0, 0, 0

    def place(self, cw, ch):
        if self.x + cw > self.width:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        if self.y + ch > self.height:
            raise SystemExit('[Error] Atlas full: lower --scale or the character set')
        pos = (self.x, self.y)
        self.x += cw
        self.row_h = max(self.row_h, ch)
        return pos


def is_space(u):
    return chr(u).isspace() or u in (0x200B, 0xFEFF)


def bake(bundle_path, font_path, asset_name, out_path=None, unity_version='2022.3.26f1', font_index=0,
         scale=1.0, dy=None, align_sample=None, extra_chars='', make_backup=True):
    bundle_path = os.path.abspath(bundle_path)
    bak_path = bundle_path + '.bak'
    if out_path is None and make_backup and not os.path.exists(bak_path):
        print(f'[Backup] Creating backup: {bak_path}')
        shutil.copyfile(bundle_path, bak_path)
    load_src = bak_path if os.path.exists(bak_path) else bundle_path
    out_path = os.path.abspath(out_path or bundle_path)

    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version
    env = UnityPy.load(load_src)
    fa_obj, fa, tex_obj = load_font_asset(env, asset_name)
    old_tex = tex_obj.read()
    old_img = np.asarray(old_tex.image.convert('RGBA'))[:, :, 3]
    AW, AH = fa['m_AtlasWidth'], fa['m_AtlasHeight']
    assert old_img.shape == (AH, AW), f'atlas texture {old_img.shape} != asset {AH}x{AW}'
    padding = fa['m_AtlasPadding']
    spread = padding + 1.0        # TMP sets material _GradientScale = padding + 1
    cell_pad = padding + 1        # SDF border rendered around each glyph rect
    point_size = fa['m_FaceInfo']['m_PointSize']
    print(f'[Asset] {asset_name}: {AW}x{AH}, pointSize={point_size}, padding={padding}, '
          f'{len(fa["m_CharacterTable"])} chars (loaded from {os.path.basename(load_src)})')

    font = TTFont(font_path, fontNumber=font_index)
    cmap, gs = font.getBestCmap(), font.getGlyphSet()
    k = point_size * scale / font['head'].unitsPerEm
    if dy is None:
        dy = glyph_center_offset(fa, font, k, align_sample)
    print(f'[Font] {font["name"].getDebugName(4)}  scale={scale}  dy={dy:+.2f}px')
    pil_font = ImageFont.truetype(font_path, size=round(point_size * scale * SUPERSAMPLE), index=font_index)

    old_glyphs = {g['m_Index']: g for g in fa['m_GlyphTable']}
    table_chars = [(c['m_Unicode'], old_glyphs[c['m_GlyphIndex']]) for c in fa['m_CharacterTable']]
    known = {u for u, _ in table_chars}
    added, skipped = [], []
    for ch in dict.fromkeys(extra_chars):
        if ord(ch) in known or ch in '\r\n':
            continue
        if ord(ch) in cmap:
            table_chars.append((ord(ch), None))
            added.append(ch)
        else:
            skipped.append(ch)

    tiles, kept = [], []   # tiles: (unicode, glyph_index, metrics, w, h, tile or None)
    for u, og in table_chars:
        name = cmap.get(u)
        if name is None:
            r, p = og['m_GlyphRect'], padding
            src = old_img[AH - (r['m_Y'] + r['m_Height']) - p: AH - r['m_Y'] + p, r['m_X'] - p: r['m_X'] + r['m_Width'] + p]
            tile = np.zeros((r['m_Height'] + 2 * cell_pad, r['m_Width'] + 2 * cell_pad), np.uint8)
            o = cell_pad - p
            tile[o:o + src.shape[0], o:o + src.shape[1]] = src
            tiles.append((u, 1_000_000 + og['m_Index'], dict(og['m_Metrics']), r['m_Width'], r['m_Height'], tile))
            kept.append(chr(u))
            continue
        gid = font.getGlyphID(name)
        adv = float(round(font['hmtx'][name][0] * k))
        bp = BoundsPen(gs); gs[name].draw(bp)
        if bp.bounds is None or is_space(u):
            metrics = dict(m_Width=0.0, m_Height=0.0, m_HorizontalBearingX=0.0, m_HorizontalBearingY=0.0, m_HorizontalAdvance=adv)
            tiles.append((u, gid, metrics, 0, 0, None))
            continue
        x0, x1 = math.floor(bp.bounds[0] * k), math.ceil(bp.bounds[2] * k)
        y0, y1 = math.floor(bp.bounds[1] * k + dy), math.ceil(bp.bounds[3] * k + dy)
        w, h = x1 - x0, y1 - y0
        # metrics are snapped to the integer glyph rect so the quad maps 1:1 onto the atlas region
        metrics = dict(m_Width=float(w), m_Height=float(h), m_HorizontalBearingX=float(x0),
                       m_HorizontalBearingY=float(y1), m_HorizontalAdvance=adv)
        tiles.append((u, gid, metrics, w, h, render_sdf(pil_font, chr(u), x0, y1, w, h, dy, cell_pad, spread)))
    print(f'[Bake] Rendered {len(tiles) - len(kept)} glyphs, kept {len(kept)} original: {"".join(kept)}')
    if added:
        print(f'[Bake] Added {len(added)} new characters: {"".join(added)}')
    if skipped:
        print(f'[Warning] Extra characters missing from the new font (not added): {"".join(skipped)}')

    atlas = np.zeros((AH, AW), np.uint8)
    packer = ShelfPacker(AW, AH)
    glyph_table, char_table, used_rects, seen = [], [], [], set()
    template_glyph = fa['m_GlyphTable'][0]
    for u, gid, metrics, w, h, tile in sorted(tiles, key=lambda t: -t[4]):
        if tile is None:
            rect = dict(m_X=0, m_Y=0, m_Width=0, m_Height=0)
        else:
            cx, cy = packer.place(tile.shape[1], tile.shape[0])
            atlas[cy:cy + tile.shape[0], cx:cx + tile.shape[1]] = tile
            # Unity texture space: origin bottom-left
            rect = dict(m_X=cx + cell_pad, m_Y=AH - (cy + cell_pad + h), m_Width=w, m_Height=h)
            used_rects.append(dict(m_X=cx, m_Y=AH - (cy + tile.shape[0]), m_Width=tile.shape[1], m_Height=tile.shape[0]))
        if gid not in seen:
            seen.add(gid)
            g = dict(template_glyph)
            g.update(m_Index=gid, m_Metrics=metrics, m_GlyphRect=rect, m_Scale=1.0, m_AtlasIndex=0)
            glyph_table.append(g)
        char_table.append(dict(m_ElementType=1, m_Unicode=u, m_GlyphIndex=gid, m_Scale=1.0))
    char_table.sort(key=lambda c: c['m_Unicode'])
    glyph_table.sort(key=lambda g: g['m_Index'])
    print(f'[Pack] Atlas rows used: {packer.y + packer.row_h}/{AH}')

    fa['m_GlyphTable'] = glyph_table
    fa['m_CharacterTable'] = char_table
    fa['m_UsedGlyphRects'] = used_rects
    fa['m_FreeGlyphRects'] = []
    fa['m_FaceInfo']['m_FamilyName'] = font['name'].getDebugName(1)
    fa['m_FaceInfo']['m_StyleName'] = font['name'].getDebugName(2)
    fa_obj.save_typetree(fa)

    rgba = np.zeros((AH, AW, 4), np.uint8)
    rgba[:, :, 3] = atlas
    old_tex.set_image(Image.fromarray(rgba, 'RGBA'), target_format=old_tex.m_TextureFormat, mipmap_count=1)
    old_tex.save()

    print('[Pack] Re-compressing bundle with LZ4...')
    data = env.file.save(packer='lz4')
    del env
    gc.collect()
    tmp_path = out_path + '.tmp'
    with open(tmp_path, 'wb') as f:
        f.write(data)
    shutil.move(tmp_path, out_path)
    if out_path != bundle_path:   # keep the game folder clean when patching in place
        Image.fromarray(atlas, 'L').save(os.path.splitext(out_path)[0] + '.atlas.png')
    print(f'[Success] Wrote {out_path} ({len(data):,} bytes)')
    return True


def main():
    ap = argparse.ArgumentParser(description='Mode C: re-bake a static TMP_FontAsset SDF atlas with a new font')
    ap.add_argument('--bundle', required=True, help='Bundle containing the TMP_FontAsset (a .bak backup is made and used as the source)')
    ap.add_argument('--font', required=True, help='Replacement TTF/OTF/TTC')
    ap.add_argument('--asset', required=True, help='TMP_FontAsset name to re-bake (e.g. "DFT_L5 SDF")')
    ap.add_argument('--out', default=None, help='Write here instead of overwriting --bundle (no backup made)')
    ap.add_argument('--unity-version', default='2022.3.26f1', help='Unity fallback version')
    ap.add_argument('--font-index', type=int, default=0, help='Face index inside a TTC')
    ap.add_argument('--scale', type=float, default=1.0, help='Glyph size relative to the original point size')
    ap.add_argument('--dy', type=float, default=None, help='Vertical shift in px (default: auto-align to old glyph centers)')
    ap.add_argument('--align-sample', default=None, help='Characters used for auto vertical alignment')
    ap.add_argument('--extra-chars', default='', help='Characters to add to the table (e.g. symbols that fell back to another font)')
    ap.add_argument('--extra-chars-file', default=None, help='UTF-8 text file of extra characters')
    ap.add_argument('--no-backup', action='store_true', help='Do not create .bak backup')
    args = ap.parse_args()
    extra = args.extra_chars
    if args.extra_chars_file:
        with open(args.extra_chars_file, encoding='utf-8') as f:
            extra += f.read()
    bake(args.bundle, args.font, args.asset, out_path=args.out, unity_version=args.unity_version,
         font_index=args.font_index, scale=args.scale, dy=args.dy, align_sample=args.align_sample,
         extra_chars=extra, make_backup=not args.no_backup)


if __name__ == '__main__':
    main()
