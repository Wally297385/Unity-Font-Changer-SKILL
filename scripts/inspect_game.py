import os, sys, json, base64, struct, argparse
from collections import Counter
import UnityPy

def detect_unity_version(game_dir):
    data_dirs = [d for d in os.listdir(game_dir) if d.endswith('_Data') and os.path.isdir(os.path.join(game_dir, d))]
    if not data_dirs:
        return '2022.3.28f1' # fallback
    data_dir = os.path.join(game_dir, data_dirs[0])
    ggm_path = os.path.join(data_dir, 'globalgamemanagers')
    if os.path.exists(ggm_path):
        try:
            with open(ggm_path, 'rb') as f:
                data = f.read(200)
                # Look for pattern like 202x.x.x
                import re
                m = re.search(rb'(20\d\d\.\d+\.\w+)', data)
                if m:
                    return m.group(1).decode('ascii', errors='ignore')
        except Exception:
            pass
    return '2022.3.28f1'

def inspect_addressables(game_dir):
    data_dirs = [d for d in os.listdir(game_dir) if d.endswith('_Data') and os.path.isdir(os.path.join(game_dir, d))]
    if not data_dirs:
        return None
    data_dir = os.path.join(game_dir, data_dirs[0])
    cat_path = os.path.join(data_dir, 'StreamingAssets', 'aa', 'catalog.json')
    if not os.path.exists(cat_path):
        return None

    with open(cat_path, 'r', encoding='utf-8') as f:
        cat = json.load(f)

    raw_keys = base64.b64decode(cat.get('m_KeyDataString', ''))
    raw_bucket = base64.b64decode(cat.get('m_BucketDataString', ''))
    raw_entries = base64.b64decode(cat.get('m_EntryDataString', ''))
    raw_extra = base64.b64decode(cat.get('m_ExtraDataString', ''))
    internal_ids = cat.get('m_InternalIds', [])
    resource_types = cat.get('m_resourceTypes', [])

    # Find resourceType index for TMPro.TMP_FontAsset
    tmp_type_idx = -1
    for idx, rt in enumerate(resource_types):
        if 'TMP_FontAsset' in rt.get('m_ClassName', ''):
            tmp_type_idx = idx
            break

    entry_count = struct.unpack_from('<i', raw_entries, 0)[0]
    font_entries = []
    for i in range(entry_count):
        vals = struct.unpack_from('<7i', raw_entries, 4 + i * 28)
        if vals[6] == tmp_type_idx or (tmp_type_idx == -1 and vals[6] == 23):
            font_entries.append((i, vals))

    # Resolve bundles
    # Parse buckets to find entry mapping
    bucket_count = struct.unpack_from('<i', raw_bucket, 0)[0]
    b_offset = 4
    bucket_map = {}
    for b in range(bucket_count):
        if b_offset >= len(raw_bucket): break
        k_offset, cnt = struct.unpack_from('<2i', raw_bucket, b_offset)
        b_offset += 8
        ents = struct.unpack_from(f'<{cnt}i', raw_bucket, b_offset)
        b_offset += cnt * 4
        bucket_map[b] = (k_offset, ents)

    font_bundles = set()
    for e_idx, vals in font_entries:
        dep_k = vals[2]
        if dep_k in bucket_map:
            k_off, ents = bucket_map[dep_k]
            for dep_e in ents:
                dep_vals = struct.unpack_from('<7i', raw_entries, 4 + dep_e * 28)
                iid = internal_ids[dep_vals[0]]
                if iid.endswith('.bundle'):
                    b_name = os.path.basename(iid)
                    font_bundles.add(b_name)

    return {
        'catalog_path': cat_path,
        'font_entry_count': len(font_entries),
        'font_bundles': list(font_bundles)
    }

def grep_count(path, needle):
    try:
        with open(path, 'rb') as f:
            return f.read().count(needle)
    except OSError:
        return 0


def analyze_text_stack(data_dir):
    """Decide which modes can work from what the managed assemblies reference."""
    managed = os.path.join(data_dir, 'Managed')
    info = {'mono': os.path.isdir(managed) and os.path.exists(os.path.join(managed, 'Assembly-CSharp.dll'))}
    if not info['mono']:
        return info   # IL2CPP: inspect GameAssembly.dll / global-metadata.dat manually
    tmp_dll = os.path.join(managed, 'Unity.TextMeshPro.dll')
    game_dll = os.path.join(managed, 'Assembly-CSharp.dll')
    # TMP 3.2+/4.x can load an external font file at runtime (Mode B); 3.0.x cannot
    info['tmp_external_path'] = grep_count(tmp_dll, b'm_SourceFontFilePath') > 0
    info['tmp_dynamic_os'] = grep_count(tmp_dll, b'DynamicOS') > 0
    # Game code walking the glyph/character tables itself = custom renderer reading a frozen copy
    info['reads_tables'] = grep_count(game_dll, b'get_characterTable') > 0 and grep_count(game_dll, b'get_glyphTable') > 0
    info['uses_tmp_components'] = (grep_count(game_dll, b'TextMeshProUGUI') + grep_count(game_dll, b'TextMeshPro\x00')) > 0
    return info


def binary_catalog_font_bundles(data_dir):
    bundles_dir = os.path.join(data_dir, 'StreamingAssets', 'aa', 'StandaloneWindows64')
    if not os.path.isdir(bundles_dir):
        return bundles_dir, []
    return bundles_dir, sorted(f for f in os.listdir(bundles_dir) if f.endswith('.bundle') and 'font' in f.lower())


def print_assets(assets):
    for a in assets:
        print(f'  [{a["type"]}] {a["name"]} (PathID: {a["path_id"]})')
        if a['type'] == 'TMP_FontAsset':
            print(f'     Mode: {a["population_mode"]}, Baked Glyphs: {a["glyph_count"]}, Family: {a["family_name"]}, '
                  f'Atlas: {a["atlas"]}, Padding: {a["padding"]}, Fallbacks: {a["fallback_count"]}')
        elif a['type'] == 'Font':
            print(f'     Embedded TTF Data: {a["font_data_len"]} bytes, Names: {a["font_names"]}')


def inspect_bundle(bundle_path, unity_version):
    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version
    env = UnityPy.load(bundle_path)
    
    font_assets = []
    for obj in env.objects:
        if obj.type.name == 'MonoBehaviour':
            try:
                tree = obj.read_typetree()
                if 'm_AtlasPopulationMode' in tree:
                    name = tree.get('m_Name', 'Unnamed_TMP')
                    pop_mode = tree.get('m_AtlasPopulationMode')
                    glyph_count = len(tree.get('m_GlyphTable', []))
                    src_font_file = tree.get('m_SourceFontFile', {})
                    src_file_path = tree.get('m_SourceFontFilePath')
                    face_info = tree.get('m_FaceInfo', {})
                    font_assets.append({
                        'type': 'TMP_FontAsset',
                        'name': name,
                        'path_id': obj.path_id,
                        'population_mode': 'Dynamic (1)' if pop_mode == 1 else 'Static (0)',
                        'glyph_count': glyph_count,
                        'source_font_file_pathid': src_font_file.get('m_PathID') if src_font_file else 0,
                        'source_font_file_path': src_file_path,
                        'family_name': face_info.get('m_FamilyName', ''),
                        'atlas': f"{tree.get('m_AtlasWidth')}x{tree.get('m_AtlasHeight')}",
                        'padding': tree.get('m_AtlasPadding'),
                        'fallback_count': len(tree.get('m_FallbackFontAssetTable', []))
                    })
            except Exception:
                pass
        elif obj.type.name == 'Font':
            try:
                tree = obj.read_typetree()
                name = tree.get('m_Name', 'Unnamed_Font')
                font_data_len = len(tree.get('m_FontData', b''))
                font_assets.append({
                    'type': 'Font',
                    'name': name,
                    'path_id': obj.path_id,
                    'font_data_len': font_data_len,
                    'font_names': tree.get('m_FontNames', [])
                })
            except Exception:
                pass

    return font_assets

def main():
    parser = argparse.ArgumentParser(description='Inspect Unity game font pipeline')
    parser.add_argument('--game-dir', required=True, help='Path to game root directory')
    args = parser.parse_args()

    game_dir = os.path.abspath(args.game_dir)
    print(f'=== Inspecting Unity Game: {game_dir} ===')

    unity_ver = detect_unity_version(game_dir)
    print(f'[Engine] Detected Unity Version: {unity_ver}')

    data_dirs = [d for d in os.listdir(game_dir) if d.endswith('_Data') and os.path.isdir(os.path.join(game_dir, d))]
    data_dir = os.path.join(game_dir, data_dirs[0]) if data_dirs else game_dir
    found_assets = []

    addr_info = inspect_addressables(game_dir)
    if addr_info:
        cnt = addr_info['font_entry_count']
        b_list = addr_info['font_bundles']
        print(f'[Addressables] Found catalog.json with {cnt} TMP FontAsset entries.')
        print(f'[Addressables] Bundles containing fonts: {b_list}')
        bundles_dir = os.path.join(data_dir, 'StreamingAssets', 'aa', 'StandaloneWindows64')
        for b in addr_info['font_bundles']:
            b_path = os.path.join(bundles_dir, b)
            if os.path.exists(b_path):
                print(f'\n--- Inspecting Font Bundle: {b} ---')
                assets = inspect_bundle(b_path, unity_ver)
                found_assets += assets
                print_assets(assets)
    elif os.path.exists(os.path.join(data_dir, 'StreamingAssets', 'aa', 'catalog.bin')):
        print('[Addressables] Binary catalog.bin detected (Addressables 1.21+). Use catalog_bin_crc.py for CRC checks.')
        bundles_dir, font_bundles = binary_catalog_font_bundles(data_dir)
        print(f'[Addressables] Bundles with "font" in the name: {font_bundles}')
        for b in font_bundles:
            print(f'\n--- Inspecting Font Bundle: {b} ---')
            assets = inspect_bundle(os.path.join(bundles_dir, b), unity_ver)
            found_assets += assets
            print_assets(assets)
        if not font_bundles:
            print('[Addressables] None found by name; inspect candidate bundles manually with inspect_bundle().')
    else:
        print('[Addressables] No catalog detected. Scanning for asset bundles...')
        for root, dirs, files in os.walk(game_dir):
            for f in files:
                if f.endswith('.bundle') or f.endswith('.assetbundle'):
                    b_path = os.path.join(root, f)
                    try:
                        assets = inspect_bundle(b_path, unity_ver)
                        if assets:
                            print(f'\n--- Found Font Assets in: {os.path.relpath(b_path, game_dir)} ---')
                            found_assets += assets
                            print_assets(assets)
                    except Exception:
                        pass

    stack = analyze_text_stack(data_dir)
    print('\n=== Text Stack ===')
    if not stack['mono']:
        print('[Scripting] IL2CPP build: check GameAssembly.dll / global-metadata.dat by hand before choosing a mode.')
        return
    print(f"[TMP] Runtime external font path (m_SourceFontFilePath): {'yes' if stack['tmp_external_path'] else 'NO (TMP 3.0.x)'}"
          f", DynamicOS: {'yes' if stack['tmp_dynamic_os'] else 'no'}")
    print(f"[Game] Assembly-CSharp reads characterTable/glyphTable: {'YES' if stack['reads_tables'] else 'no'}"
          f", uses TextMeshPro components: {'yes' if stack['uses_tmp_components'] else 'NO'}")

    static_assets = [a for a in found_assets if a['type'] == 'TMP_FontAsset' and a['population_mode'].startswith('Static') and a['glyph_count']]
    print('\n=== Recommendation ===')
    if stack['reads_tables']:
        print('Mode C (bake_static_atlas.py): the game copies glyph data out of the font asset into its own renderer,')
        print('so Dynamic assets (Mode A/B) render nothing there. Re-bake the static atlas of the asset that serves your language')
        print('(follow the language root asset\'s fallback list; see references/static_atlas_rebake.md).')
    elif static_assets and not stack['tmp_external_path']:
        print('Mode C: static assets found and this TMP version cannot load an external font file (Mode B would show blanks).')
    elif static_assets:
        print('Mode B or Mode C: static assets found. Mode C keeps the original rendering path and is the safer choice.')
    elif any(a['type'] == 'Font' for a in found_assets):
        print('Mode A: dynamic assets with embedded Font data found.')
    else:
        print('No clear match; inspect the font assets above manually.')

if __name__ == '__main__':
    main()
