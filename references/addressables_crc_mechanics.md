# Unity Addressables CRC Validation Bypass

When modding Unity games that use the Addressables system, modifying a `.bundle` file will change its hash. By default, Unity performs a Cyclic Redundancy Check (CRC) when loading bundles. If the hash of the loaded bundle does not match the expected hash stored in `catalog.json`, the game will crash or refuse to load the bundle.

This document details how to bypass this validation mechanism.

## The `catalog.json` Structure

The `catalog.json` file (typically found in `StreamingAssets/aa/catalog.json` or similar) is the master ledger for all Addressable assets. It contains metadata about every bundle.

The crucial information is stored in a compressed format within these two keys:
1.  `m_EntryDataString`: A base64-encoded binary string containing an array of structs. These structs map internal asset IDs to their metadata locations in `m_ExtraDataString`.
2.  `m_ExtraDataString`: A base64-encoded binary string containing the actual JSON configuration chunks (UTF-16LE encoded) for each bundle.

## The CRC Field

Inside `m_ExtraDataString`, the configuration chunks look something like this (encoded in UTF-16LE):
`{"m_Crc":123456789,"m_Hash":"abcdef123456...","m_Dependencies":[]}`

The engine reads `m_Crc` to perform validation.
**The Bypass:** If `m_Crc` is set to `0`, the Unity engine skips CRC validation for that bundle entirely.

## The Bypass Technique

To safely bypass the CRC check without corrupting the `catalog.json` file, we must modify the `m_Crc` value to `0` *in place*, preserving the exact byte length of the UTF-16LE string. Because `m_ExtraDataString` is parsed using exact offsets defined in `m_EntryDataString`, adding or removing even a single byte will misalign all subsequent data chunks and break the game.

### Step-by-Step Implementation

1.  **Decode Data:** Base64 decode both `m_EntryDataString` and `m_ExtraDataString`.
2.  **Locate Bundle Metadata:**
    *   Parse the header of the `m_EntryDataString` byte array (first 4 bytes as an integer) to get the `entry_count`.
    *   Iterate through the entries (each entry is 28 bytes). Read the first integer (internal ID index) and the fifth integer (offset in `m_ExtraDataString`).
    *   Match the internal ID to the target bundle name.
3.  **Patch the Chunk:**
    *   Go to the offset in `m_ExtraDataString`.
    *   Search forward for the UTF-16LE string `"m_Crc":`.
    *   Read the existing integer value.
    *   Replace the integer value with `0`.
    *   **Crucial Step:** Pad the replacement string with spaces (in UTF-16LE, a space is `0x20 0x00`) so that the length of the patched chunk is exactly identical to the original chunk. For example, replacing `"m_Crc":12345` with `"m_Crc":0` requires 4 spaces of padding: `"m_Crc":    0`.
4.  **Save:** Base64 encode the modified `m_ExtraDataString` byte array and save it back to `catalog.json`.

By following this precise padding technique, the CRC check is disabled for the modified bundle, and the integrity of the catalog's data structure is preserved.

## Binary Catalogs (`catalog.bin`, Addressables 1.21+)

Newer Addressables builds can ship `StreamingAssets/aa/catalog.bin` (see `m_CatalogLocations` in `aa/settings.json`). It is a `BinaryStorageBuffer`, not JSON, so `patch_catalog_crc.py` does not apply.

Each bundle's `AssetBundleRequestOptions` is serialized as a fixed-size record that is written right after the bundle's internal name string (length-prefixed, the AssetBundle object's name without `.bundle`):

```
uint32 hashId        // offset of the Hash128 object
uint32 bundleNameId  // offset of the bundle name string
uint32 crc           // 0 = CRC check disabled
uint32 bundleSize    // original file size in bytes
...                  // timeout / retry / flags
```

`catalog_bin_crc.py` finds that record, accepts it only if `bundleSize` equals the original bundle's file size (so a wrong match is never patched), prints the CRC, and with `--patch` writes `0` into the 4-byte CRC field in place. Every field is fixed width, so no other offsets move.

Check before patching: many games build local bundles with CRC disabled (`crc == 0`), in which case a modified bundle loads as-is. A changed `bundleSize` does not matter for local bundles loaded from disk.
