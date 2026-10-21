"""Check a replacement font against what a TMP_FontAsset (and optionally the game's text) needs.

Run this before Mode C. It reports characters the new font is missing or draws as empty
outlines, split into "used by the game text" and "only in the asset's character table".
"""
import argparse, glob, re

import UnityPy
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

UTF8_RUN = re.compile(rb'(?:[\xf0-\xf4][\x80-\xbf]{3}|[\xe0-\xef][\x80-\xbf]{2}|[\xc2-\xdf][\x80-\xbf]|[\x20-\x7e])+')


def harvest_text_chars(patterns):
    """Collect characters from UTF-8 text runs inside (possibly binary) text containers."""
    used = set()
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            with open(path, 'rb') as f:
                data = f.read()
            for m in UTF8_RUN.finditer(data):
                s = m.group().decode('utf-8', errors='ignore')
                if any(ord(c) > 0x7f for c in s):
                    used.update(s)
    return used


def bundle_char_tables(bundle, unity_version):
    """Return {asset name: chars} and {root asset name: [fallback asset names]}."""
    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version
    env = UnityPy.load(bundle)
    trees = {}
    for obj in env.objects:
        if obj.type.name == 'MonoBehaviour':
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            if 'm_CharacterTable' in tree:
                trees[obj.path_id] = tree
    tables = {t['m_Name']: {chr(c['m_Unicode']) for c in t['m_CharacterTable']} for t in trees.values() if t['m_CharacterTable']}
    chains = {t['m_Name']: [trees[f['m_PathID']]['m_Name'] for f in t.get('m_FallbackFontAssetTable', []) if f['m_PathID'] in trees]
              for t in trees.values() if t.get('m_FallbackFontAssetTable')}
    return tables, chains


def classify(font, chars):
    cmap, gs = font.getBestCmap(), font.getGlyphSet()
    res = {'ok': [], 'missing': [], 'empty': []}
    for c in sorted(chars):
        if ord(c) not in cmap:
            res['missing'].append(c)
        elif c.isspace():
            res['ok'].append(c)
        else:
            bp = BoundsPen(gs); gs[cmap[ord(c)]].draw(bp)
            res['ok' if bp.bounds else 'empty'].append(c)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--bundle', required=True, help='Bundle holding the TMP_FontAsset(s)')
    ap.add_argument('--asset', required=True, help='TMP_FontAsset to be replaced')
    ap.add_argument('--font', required=True, help='Replacement TTF/OTF/TTC')
    ap.add_argument('--font-index', type=int, default=0)
    ap.add_argument('--text', nargs='*', default=[], help='Glob(s) of game text files (UTF-8, may be inside binary containers)')
    ap.add_argument('--chain', nargs='*', default=None,
                    help='Font assets that can serve the text (default: fallback lists of root assets that include --asset)')
    ap.add_argument('--unity-version', default='2022.3.26f1')
    args = ap.parse_args()

    font = TTFont(args.font, fontNumber=args.font_index)
    name = font['name']
    print(f'[Font] {name.getDebugName(4)}: {font["maxp"].numGlyphs} glyphs, {len(font.getBestCmap())} cmap entries')
    tables, chains = bundle_char_tables(args.bundle, args.unity_version)
    if args.asset not in tables:
        raise SystemExit(f'[Error] "{args.asset}" not found. Assets with tables: {list(tables)}')
    target = tables[args.asset]
    chain = args.chain
    if chain is None:
        roots = [r for r, fb in chains.items() if args.asset in fb]
        chain = sorted({a for r in roots for a in chains[r]} | {args.asset})
        if roots:
            print(f'[Chain] "{args.asset}" is a fallback of {roots}; text chars are checked against {chain}')
    any_table = set().union(*(tables.get(a, set()) for a in chain))

    sections = []
    if args.text:
        used = harvest_text_chars(args.text)
        # binary containers yield noise; keep characters some game font actually provides
        real = used & any_table
        print(f'[Text] {len(used)} distinct non-ASCII-run chars harvested, {len(real)} are in the font chain '
              f'({len(used) - len(real)} ignored as noise)')
        sections.append(('Used by game text', real))
        served_elsewhere = real - target
        if served_elsewhere:
            print(f'[Text] Used but not in "{args.asset}" (served by fallback assets): {"".join(sorted(served_elsewhere))}')
            print('       -> pass them to bake_static_atlas.py --extra-chars to draw them with the new font too')
    sections.append((f'"{args.asset}" character table', target))

    for label, chars in sections:
        res = classify(font, chars)
        print(f'\n== {label}: {len(chars)} chars ==')
        for key in ('ok', 'missing', 'empty'):
            print(f'  {key}: {len(res[key])}')
            if key != 'ok' and res[key]:
                print('   ', ' '.join(f'{c}(U+{ord(c):04X})' for c in res[key]))


if __name__ == '__main__':
    main()
