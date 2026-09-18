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
                        'family_name': face_info.get('m_FamilyName', '')
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

    addr_info = inspect_addressables(game_dir)
    if addr_info:
        cnt = addr_info['font_entry_count']
        b_list = addr_info['font_bundles']
        print(f'[Addressables] Found catalog.json with {cnt} TMP FontAsset entries.')
        print(f'[Addressables] Bundles containing fonts: {b_list}')
        
        data_dirs = [d for d in os.listdir(game_dir) if d.endswith('_Data')]
        bundles_dir = os.path.join(game_dir, data_dirs[0], 'StreamingAssets', 'aa', 'StandaloneWindows64')
        for b in addr_info['font_bundles']:
            b_path = os.path.join(bundles_dir, b)
            if os.path.exists(b_path):
                print(f'\n--- Inspecting Font Bundle: {b} ---')
                assets = inspect_bundle(b_path, unity_ver)
                for a in assets:
                    t_type = a['type']
                    t_name = a['name']
                    t_pid = a['path_id']
                    print(f'  [{t_type}] {t_name} (PathID: {t_pid})')
                    if a['type'] == 'TMP_FontAsset':
                        pop = a['population_mode']
                        gc = a['glyph_count']
                        fam = a['family_name']
                        print(f'     Mode: {pop}, Baked Glyphs: {gc}, Family: {fam}')
                    elif a['type'] == 'Font':
                        fd_len = a['font_data_len']
                        fn_names = a['font_names']
                        print(f'     Embedded TTF Data: {fd_len} bytes, Names: {fn_names}')
    else:
        print('[Addressables] No catalog.json detected. Scanning StreamingAssets for asset bundles...')
        # Scan for bundles
        for root, dirs, files in os.walk(game_dir):
            for f in files:
                if f.endswith('.bundle') or f.endswith('.assetbundle'):
                    b_path = os.path.join(root, f)
                    try:
                        assets = inspect_bundle(b_path, unity_ver)
                        if assets:
                            print(f'\n--- Found Font Assets in: {os.path.relpath(b_path, game_dir)} ---')
                            for a in assets:
                                at = a['type']
                                an = a['name']
                                ap = a['path_id']
                                print(f'  [{at}] {an} (PathID: {ap})')
                    except Exception:
                        pass

if __name__ == '__main__':
    main()
