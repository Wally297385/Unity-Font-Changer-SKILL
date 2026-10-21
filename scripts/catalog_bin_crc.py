"""Read (and optionally zero) a bundle's CRC in a binary Addressables catalog (catalog.bin).

Addressables 1.21+ can ship `catalog.bin` instead of `catalog.json`; `patch_catalog_crc.py` only
handles the JSON form. In the binary catalog each bundle's AssetBundleRequestOptions is stored as
a fixed-size record written right after the bundle's internal name string:

    uint32 hashId, uint32 bundleNameId, uint32 crc, uint32 bundleSize, ...

The internal name is the AssetBundle object's name inside the bundle (e.g. "7d93a5de...bundle"
-> stored without ".bundle"). The record is accepted only if its bundleSize equals the original
bundle file size, so a wrong match is refused instead of patched.
"""
import argparse, os, shutil, struct

import UnityPy


def bundle_internal_name(path, unity_version):
    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version
    env = UnityPy.load(path)
    for obj in env.objects:
        if obj.type.name == 'AssetBundle':
            name = obj.read_typetree().get('m_Name', '')
            return name[:-7] if name.endswith('.bundle') else name
    raise SystemExit(f'[Error] No AssetBundle object in {path}')


def find_record(cat, name, expected_size):
    needle = struct.pack('<I', len(name)) + name.encode('ascii')
    hits = []
    start = 0
    while (i := cat.find(needle, start)) != -1:
        rec = i + len(needle)
        hash_id, name_id, crc, size = struct.unpack_from('<4I', cat, rec)
        hits.append((rec, crc, size))
        start = i + 1
    for rec, crc, size in hits:
        if size == expected_size:
            return rec, crc, size
    return None, hits


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--catalog', required=True, help='Path to catalog.bin')
    ap.add_argument('--bundles', nargs='+', required=True, help='Bundle file(s); their .bak (original) is used for name/size when present')
    ap.add_argument('--patch', action='store_true', help='Set the CRC of each matched bundle to 0 (backs up catalog.bin first)')
    ap.add_argument('--unity-version', default='2022.3.26f1')
    args = ap.parse_args()

    with open(args.catalog, 'rb') as f:
        cat = bytearray(f.read())
    patched = 0
    for b in args.bundles:
        original = b + '.bak' if os.path.exists(b + '.bak') else b
        name = bundle_internal_name(original, args.unity_version)
        size = os.path.getsize(original)
        found = find_record(cat, name, size)
        if found[0] is None:
            print(f'[Warning] {os.path.basename(b)}: no record with bundleSize={size} after name "{name}" '
                  f'(candidates: {found[1]}) - not touched')
            continue
        rec, crc, _ = found
        print(f'[Catalog] {os.path.basename(b)}: internal name {name}, size {size}, CRC = {crc} (0x{crc:08X}) at offset {rec + 8}')
        if crc == 0:
            print('          CRC already 0 -> no CRC check, modified bundle loads as-is')
        elif args.patch:
            struct.pack_into('<I', cat, rec + 8, 0)
            print('          CRC set to 0')
            patched += 1
        else:
            print('          CRC is checked -> rerun with --patch after modifying this bundle')
    if patched:
        bak = args.catalog + '.bak'
        if not os.path.exists(bak):
            shutil.copyfile(args.catalog, bak)
            print(f'[Backup] {bak}')
        with open(args.catalog, 'wb') as f:
            f.write(cat)
        print(f'[Success] Patched {patched} CRC value(s) in {args.catalog}')


if __name__ == '__main__':
    main()
