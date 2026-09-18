import os, sys, json, base64, struct, argparse

def patch_catalog_crc(catalog_path, target_bundle_names, crc_value=0, make_backup=True):
    catalog_path = os.path.abspath(catalog_path)
    if not os.path.exists(catalog_path):
        raise FileNotFoundError(f'catalog.json not found: {catalog_path}')

    if make_backup:
        bak_path = catalog_path + '.bak'
        if not os.path.exists(bak_path):
            import shutil
            print(f'[Backup] Backing up catalog to: {bak_path}')
            shutil.copyfile(catalog_path, bak_path)

    with open(catalog_path, 'r', encoding='utf-8') as f:
        cat = json.load(f)

    entries = base64.b64decode(cat['m_EntryDataString'])
    extra = bytearray(base64.b64decode(cat['m_ExtraDataString']))
    internal_ids = cat['m_InternalIds']
    entry_count = struct.unpack_from('<i', entries, 0)[0]

    # Map bundle names to entry data indices
    bundle_entries = {}
    for i in range(entry_count):
        vals = struct.unpack_from('<7i', entries, 4 + i * 28)
        iid = internal_ids[vals[0]]
        for b in target_bundle_names:
            if b.lower() in iid.lower():
                bundle_entries[b] = (i, vals[4])

    print(f'[Catalog] Found {len(bundle_entries)} / {len(target_bundle_names)} target bundles in catalog.')

    patched_count = 0
    for b, (ent_idx, d_idx) in bundle_entries.items():
        chunk = extra[d_idx:d_idx+700]
        pos = chunk.find('"m_Crc":'.encode('utf-16le'))
        if pos == -1:
            print(f'[Warning] "m_Crc" not found for bundle {b} at data index {d_idx}')
            continue

        abs_pos = d_idx + pos
        comma_pos = extra.find(','.encode('utf-16le'), abs_pos)
        old_slice = bytes(extra[abs_pos:comma_pos])
        old_str = old_slice.decode('utf-16le')

        if old_str.replace(' ', '').endswith(f':{crc_value}'):
            print(f'[Skip] Bundle {b} already has m_Crc={crc_value} ({old_str})')
            continue

        colon_idx = old_str.find(':')
        digits = old_str[colon_idx+1:]
        val_str = str(crc_value)
        # Pad with spaces to keep exact byte length identical
        new_str = old_str[:colon_idx+1] + (' ' * (len(digits) - len(val_str))) + val_str
        assert len(new_str) == len(old_str), f'Length mismatch: "{old_str}" vs "{new_str}"'

        extra[abs_pos:comma_pos] = new_str.encode('utf-16le')
        print(f'[Patch] Patched Entry {ent_idx} ({b}): "{old_str}" -> "{new_str}"')
        patched_count += 1

    # Check total length unchanged
    assert len(extra) == len(base64.b64decode(cat['m_ExtraDataString'])), 'ExtraDataString length changed!'

    cat['m_ExtraDataString'] = base64.b64encode(extra).decode('ascii')
    with open(catalog_path, 'w', encoding='utf-8') as f:
        json.dump(cat, f, separators=(',', ':'))

    print(f'[Success] Saved {catalog_path} with {patched_count} entries patched to CRC {crc_value}!')
    return True

def main():
    parser = argparse.ArgumentParser(description='Patch Addressables catalog.json to bypass CRC checks (m_Crc: 0)')
    parser.add_argument('--catalog', required=True, help='Path to catalog.json')
    parser.add_argument('--bundles', required=True, help='Comma-separated bundle filenames to bypass CRC')
    parser.add_argument('--crc', type=int, default=0, help='New CRC value (default: 0 to bypass)')
    parser.add_argument('--no-backup', action='store_true', help='Do not create .bak backup')
    args = parser.parse_args()

    target_bundles = [b.strip() for b in args.bundles.split(',') if b.strip()]
    patch_catalog_crc(
        catalog_path=args.catalog,
        target_bundle_names=target_bundles,
        crc_value=args.crc,
        make_backup=not args.no_backup
    )

if __name__ == '__main__':
    main()
