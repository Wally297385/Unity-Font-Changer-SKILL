"""Render sample text from one or more font bundles, approximating an in-game TMP SDF style.

Each bundle becomes one panel, stacked top to bottom, so an original and a re-baked bundle can be
compared before launching the game. By default the SDF is shaded like the TMP SDF shader with the
given FaceDilate / OutlineWidth: dilate grows the face, the dark outline is centred on the dilated
edge, plus a vertical face gradient and a soft drop shadow. --plain shows the bare SDF instead.
Match --dilate/--outline to the game's material values, otherwise bold fonts look lighter here
than in game. Characters missing from the asset's table are left as a blank gap.
"""
import argparse

import numpy as np
import UnityPy
from PIL import Image, ImageFilter

DEFAULT_LINES = ['繁體中文字型預覽：遊戲資料的保存', '天地玄黃，宇宙洪荒。日月盈昃，辰宿列張。',
                 '「確定要讀取嗎？」…！？　HP 20% ABC abc 0123',
                 'The quick brown fox jumps over the lazy dog.']


def load(path, asset, unity_version):
    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version
    env = UnityPy.load(path)
    fa = None
    for o in env.objects:
        if o.type.name == 'MonoBehaviour':
            try:
                t = o.read_typetree()
            except Exception:
                continue
            if t.get('m_Name') == asset and 'm_GlyphTable' in t:
                fa = t
    if fa is None:
        raise SystemExit(f'[Error] "{asset}" not found in {path}')
    tex = next(o for o in env.objects if o.path_id == fa['m_AtlasTextures'][0]['m_PathID']).read()
    atlas = np.asarray(tex.image.convert('RGBA'))[:, :, 3].astype(np.float32) / 255
    glyphs = {g['m_Index']: g for g in fa['m_GlyphTable']}
    chars = {c['m_Unicode']: glyphs[c['m_GlyphIndex']] for c in fa['m_CharacterTable']}
    return chars, atlas, fa['m_AtlasPadding'], fa['m_FaceInfo']['m_PointSize']


def sdf_field(lines, chars, atlas, padding, em, zoom, line_height, width):
    """Composite every glyph's SDF tile into one field (max), upscaled by zoom."""
    H = atlas.shape[0]
    field = np.zeros((int(line_height * (len(lines) + 0.5) * zoom), width * zoom), np.float32)
    for li, line in enumerate(lines):
        pen, base = 16.0, (li + 1) * line_height - line_height * 0.25
        for ch in line:
            g = chars.get(ord(ch))
            if g is None:
                pen += em
                continue
            m, r = g['m_Metrics'], g['m_GlyphRect']
            if r['m_Width']:
                P = padding
                tile = atlas[H - (r['m_Y'] + r['m_Height']) - P: H - r['m_Y'] + P, r['m_X'] - P: r['m_X'] + r['m_Width'] + P]
                t = np.asarray(Image.fromarray(tile).resize((tile.shape[1] * zoom, tile.shape[0] * zoom), Image.BILINEAR))
                x = int(round((pen + m['m_HorizontalBearingX'] - P) * zoom))
                y = int(round((base - m['m_HorizontalBearingY'] - P) * zoom))
                h, w = min(t.shape[0], field.shape[0] - y), min(t.shape[1], field.shape[1] - x)
                if h > 0 and w > 0:
                    field[y:y + h, x:x + w] = np.maximum(field[y:y + h, x:x + w], t[:h, :w])
            pen += m['m_HorizontalAdvance']
    return field


def shade(field, padding, zoom, line_height, dilate, outline_width, game):
    gradient_scale = padding + 1.0
    aa = 2 * gradient_scale * zoom           # alpha 0..1 spans 2 * spread texels
    if game:
        ratio_a = (gradient_scale - 1) / gradient_scale   # TMP _ScaleRatioA when dilate + outline <= 1
        edge = 0.5 - dilate * ratio_a * 0.5
        half_outline = outline_width * ratio_a * 0.5
        face_t, outline_t = edge + half_outline, edge - half_outline
    else:
        face_t = outline_t = 0.5
    face = np.clip((field - face_t) * aa + 0.5, 0, 1)
    outl = np.clip((field - outline_t) * aa + 0.5, 0, 1)
    H, W = field.shape
    bg = np.empty((H, W, 3), np.float32)
    bg[:] = (13, 52, 98)
    if game:
        shadow = np.asarray(Image.fromarray((outl * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3 * zoom)), np.float32) / 255
        bg *= 1 - np.roll(shadow, (2 * zoom, 2 * zoom), axis=(0, 1))[..., None] * 0.55
        out = bg * (1 - outl[..., None]) + np.array([38, 42, 58], np.float32) * outl[..., None]
        period = line_height * zoom
        rows = ((np.arange(H) + period * 0.25) % period / period)[:, None, None]
        face_col = np.array([250, 250, 245], np.float32) * (1 - rows) + np.array([190, 196, 204], np.float32) * rows
    else:
        out, face_col = bg, np.array([235, 235, 225], np.float32)
    out = out * (1 - face[..., None]) + face_col * face[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('bundles', nargs='+', help='Font bundles to compare (one panel each)')
    ap.add_argument('--asset', required=True, help='TMP_FontAsset name')
    ap.add_argument('--out', required=True, help='Output PNG')
    ap.add_argument('--text-file', default=None, help='UTF-8 file with sample lines (default: built-in CJK/Latin sample)')
    ap.add_argument('--unity-version', default='2022.3.26f1')
    ap.add_argument('--zoom', type=int, default=2)
    ap.add_argument('--line-height', type=int, default=None, help='px at atlas scale (default: 1.25 x point size)')
    ap.add_argument('--width', type=int, default=None, help='px at atlas scale (default: 25 x point size)')
    ap.add_argument('--dilate', type=float, default=0.3, help='Material _FaceDilate used by the game')
    ap.add_argument('--outline', type=float, default=0.2, help='Material _OutlineWidth used by the game')
    ap.add_argument('--plain', action='store_true', help='Bare SDF threshold instead of game style')
    args = ap.parse_args()

    lines = DEFAULT_LINES
    if args.text_file:
        with open(args.text_file, encoding='utf-8') as f:
            lines = [l.rstrip('\n') for l in f if l.strip()]
    panels = []
    for b in args.bundles:
        chars, atlas, padding, em = load(b, args.asset, args.unity_version)
        lh = args.line_height or round(em * 1.25)
        field = sdf_field(lines, chars, atlas, padding, em, args.zoom, lh, args.width or em * 25)
        panels.append(shade(field, padding, args.zoom, lh, args.dilate, args.outline, not args.plain))
    out = Image.new('RGB', (max(p.width for p in panels), sum(p.height for p in panels) + 10 * (len(panels) - 1)))
    y = 0
    for p in panels:
        out.paste(p, (0, y))
        y += p.height + 10
    out.save(args.out)
    print(f'[Preview] {args.out}')


if __name__ == '__main__':
    main()
