import os, sys, shutil, argparse
import UnityPy

def inject_font(bundle_path, font_path, unity_version='2022.3.28f1', target_names=None, make_backup=True):
    bundle_path = os.path.abspath(bundle_path)
    font_path = os.path.abspath(font_path)

    if not os.path.exists(bundle_path):
        raise FileNotFoundError(f'Bundle not found: {bundle_path}')
    if not os.path.exists(font_path):
        raise FileNotFoundError(f'Font file not found: {font_path}')

    with open(font_path, 'rb') as f:
        font_bytes = f.read()
    print(f'[Font] Loaded replacement font: {font_path} ({len(font_bytes)} bytes)')

    bak_path = bundle_path + '.bak'
    if make_backup:
        if not os.path.exists(bak_path):
            print(f'[Backup] Creating backup: {bak_path}')
            shutil.copyfile(bundle_path, bak_path)
        else:
            print(f'[Backup] Backup already exists: {bak_path}')

    load_src = bak_path if os.path.exists(bak_path) else bundle_path

    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version
    env = UnityPy.load(load_src)

    targets = [t.strip().lower() for t in target_names.split(',')] if target_names and target_names.lower() != 'all' else None

    replaced_count = 0
    for obj in env.objects:
        if obj.type.name == 'Font':
            try:
                tree = obj.read_typetree()
                font_name = tree.get('m_Name', '')
                if targets is None or font_name.lower() in targets or 'all' in targets:
                    old_len = len(tree.get('m_FontData', b''))
                    tree['m_FontData'] = font_bytes
                    curr_names = tree.get('m_FontNames', [])
                    font_base = os.path.splitext(os.path.basename(font_path))[0]
                    if font_base not in curr_names:
                        tree['m_FontNames'] = [font_base] + curr_names
                    obj.save_typetree(tree)
                    print(f'[Inject] Replaced Font "{font_name}" (PathID: {obj.path_id}): {old_len} -> {len(font_bytes)} bytes')
                    replaced_count += 1
            except Exception as e:
                print(f'[Warning] Failed to inspect Font {obj.path_id}: {e}')

    if replaced_count == 0:
        print('[Error] No matching Font assets were found to replace!')
        return False

    tmp_path = bundle_path + '.tmp'
    print(f'[Pack] Re-compressing bundle with LZ4 chunk packer...')
    out_data = env.file.save(packer='lz4')
    with open(tmp_path, 'wb') as f:
        f.write(out_data)

    del env
    import gc
    gc.collect()

    print(f'[Verify] Reloading {tmp_path} to verify byte integrity...')
    env_v = UnityPy.load(tmp_path)
    verify_count = 0
    for obj in env_v.objects:
        if obj.type.name == 'Font':
            tree = obj.read_typetree()
            font_name = tree.get('m_Name', '')
            if targets is None or font_name.lower() in targets or 'all' in targets:
                assert len(tree['m_FontData']) == len(font_bytes), f'Size mismatch in {font_name}!'
                verify_count += 1
    assert verify_count == replaced_count, 'Verification count mismatch!'
    del env_v
    gc.collect()

    shutil.move(tmp_path, bundle_path)
    print(f'[Success] Successfully replaced {replaced_count} fonts in {os.path.basename(bundle_path)}!')
    return True

def main():
    parser = argparse.ArgumentParser(description='Mode A: Inject embedded TTF font into Unity AssetBundle')
    parser.add_argument('--bundle', required=True, help='Path to target AssetBundle')
    parser.add_argument('--font', required=True, help='Path to source TTF font')
    parser.add_argument('--unity-version', default='2022.3.28f1', help='Unity fallback version (e.g. 2022.3.28f1)')
    parser.add_argument('--target-names', default='all', help='Comma-separated font names to target, or "all"')
    parser.add_argument('--no-backup', action='store_true', help='Do not create .bak backup')
    args = parser.parse_args()

    inject_font(
        bundle_path=args.bundle,
        font_path=args.font,
        unity_version=args.unity_version,
        target_names=args.target_names,
        make_backup=not args.no_backup
    )

if __name__ == '__main__':
    main()
