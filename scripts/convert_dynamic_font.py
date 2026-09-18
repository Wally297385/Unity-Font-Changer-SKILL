import os, sys, shutil, argparse
import UnityPy

def convert_dynamic(bundle_path, font_relative_path, unity_version='2023.2.4f1', target_tmp_name=None, atlas_dim=2048, make_backup=True):
    bundle_path = os.path.abspath(bundle_path)
    if not os.path.exists(bundle_path):
        raise FileNotFoundError(f'Bundle not found: {bundle_path}')

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

    converted_count = 0
    atlas_texture_pids = set()

    for obj in env.objects:
        if obj.type.name == 'MonoBehaviour':
            try:
                tree = obj.read_typetree()
                if 'm_AtlasPopulationMode' in tree:
                    name = tree.get('m_Name', '')
                    if target_tmp_name is None or target_tmp_name.lower() in name.lower():
                        old_mode = tree.get('m_AtlasPopulationMode')
                        tree['m_AtlasPopulationMode'] = 1 # Dynamic
                        tree['m_SourceFontFilePath'] = font_relative_path
                        tree['m_SourceFontFile'] = {'m_FileID': 0, 'm_PathID': 0}
                        tree['m_GlyphTable'] = []
                        tree['m_CharacterTable'] = []
                        tree['m_AtlasWidth'] = atlas_dim
                        tree['m_AtlasHeight'] = atlas_dim
                        tree['m_AtlasPadding'] = 9

                        # Track atlas texture path ids
                        atlas_texs = tree.get('m_AtlasTextures', [])
                        for at in atlas_texs:
                            if at.get('m_PathID'):
                                atlas_texture_pids.add(at['m_PathID'])

                        obj.save_typetree(tree)
                        print(f'[Convert] TMP_FontAsset "{name}" (PathID: {obj.path_id}) converted to Dynamic mode.')
                        print(f'          Redirected m_SourceFontFilePath -> "{font_relative_path}"')
                        converted_count += 1
            except Exception as e:
                print(f'[Warning] Failed to inspect MonoBehaviour {obj.path_id}: {e}')

    if converted_count == 0:
        print('[Error] No matching TMP_FontAsset found in bundle!')
        return False

    # Clean Atlas Texture2D if found
    for obj in env.objects:
        if obj.type.name == 'Texture2D' and (obj.path_id in atlas_texture_pids or 'atlas' in getattr(obj.read(), 'name', '').lower()):
            try:
                tree = obj.read_typetree()
                tex_name = tree.get('m_Name', 'Atlas')
                tree['m_Width'] = atlas_dim
                tree['m_Height'] = atlas_dim
                tree['m_CompleteImageSize'] = atlas_dim * atlas_dim
                tree['m_TextureFormat'] = 1 # Alpha8
                tree['m_MipCount'] = 1
                tree['m_IsReadable'] = True
                tree['image data'] = b'\x00' * (atlas_dim * atlas_dim)
                obj.save_typetree(tree)
                print(f'[Texture] Reset Atlas Texture2D "{tex_name}" (PathID: {obj.path_id}) to {atlas_dim}x{atlas_dim} Alpha8 buffer.')
            except Exception as e:
                print(f'[Warning] Could not reset Atlas Texture2D: {e}')

    tmp_path = bundle_path + '.tmp'
    print('[Pack] Re-compressing bundle with LZ4 chunk packer...')
    out_data = env.file.save(packer='lz4')
    with open(tmp_path, 'wb') as f:
        f.write(out_data)

    del env
    import gc
    gc.collect()

    print(f'[Verify] Reloading {tmp_path} to verify dynamic settings...')
    env_v = UnityPy.load(tmp_path)
    for obj in env_v.objects:
        if obj.type.name == 'MonoBehaviour':
            tree = obj.read_typetree()
            if 'm_AtlasPopulationMode' in tree:
                assert tree['m_AtlasPopulationMode'] == 1, 'Failed to persist dynamic mode!'
                assert tree['m_SourceFontFilePath'] == font_relative_path, 'Path mismatch!'

    del env_v
    gc.collect()

    shutil.move(tmp_path, bundle_path)
    print(f'[Success] Successfully converted {converted_count} TMP_FontAssets in {os.path.basename(bundle_path)}!')
    return True

def main():
    parser = argparse.ArgumentParser(description='Mode B: Convert Static TMP_FontAsset to Dynamic SDF with external TTF redirection')
    parser.add_argument('--bundle', required=True, help='Path to target AssetBundle')
    parser.add_argument('--font-relative-path', required=True, help='Relative path to external font (e.g. GameName_Data/StreamingAssets/aa/font.ttf)')
    parser.add_argument('--unity-version', default='2023.2.4f1', help='Unity fallback version')
    parser.add_argument('--target-name', default=None, help='Target TMP_FontAsset name (default: all in bundle)')
    parser.add_argument('--atlas-size', type=int, default=2048, help='Dynamic atlas dimension (default: 2048)')
    parser.add_argument('--no-backup', action='store_true', help='Do not create .bak backup')
    args = parser.parse_args()

    convert_dynamic(
        bundle_path=args.bundle,
        font_relative_path=args.font_relative_path,
        unity_version=args.unity_version,
        target_tmp_name=args.target_name,
        atlas_dim=args.atlas_size,
        make_backup=not args.no_backup
    )

if __name__ == '__main__':
    main()
