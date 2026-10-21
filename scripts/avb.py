"""AVB footers for vayu's boot and dtbo partitions.

The 5.4 image this phone runs carries an AVB hash footer on both partitions
whose vbmeta uses algorithm NONE: no signature, just a salted SHA-256 of the
image in a hash descriptor. That is why a custom kernel can boot at all on an
unlocked vayu - anybody can compute the digest, while a signed image would need
Xiaomi's key.

The footer is not optional. Flashing a boot image that has no footer makes ABL
answer, in about one second and without ever entering the kernel:

    fastboot boot vayu-boot.img
    Booting  FAILED (remote: 'Failed to load/authenticate boot image: Load Error')

That was measured on this device. So `mkbootimg.py build` and `mkdtbo.py build`
put a footer on the image and pad it to the partition size, and this module is
how they do it: avbtool (vendored in third_party/, MIT, from AOSP) writes the
footer, and the parser below reads it back so verification does not depend on
the tool that wrote it.
"""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

AVBTOOL = Path(__file__).with_name("third_party") / "avbtool.py"

FOOTER_MAGIC = b"AVBf"
VBMETA_MAGIC = b"AVB0"
FOOTER_SIZE = 64
HEADER_SIZE = 256
ALGORITHM_NONE = 0

# All AVB structures are big-endian; the footer is the last 64 bytes of the
# partition and points at the vbmeta blob that follows the image itself.
FOOTER = dict(magic=4, version=(4, 8), original_image_size=12,
              vbmeta_offset=20, vbmeta_size=28)

HEADER = dict(
    magic=4,
    required=(4, 8),                       # major, minor
    auth_block_size=12, aux_block_size=20,
    algorithm=28,
    descriptors_offset=96, descriptors_size=104,
    rollback_index=112, flags=120, rollback_index_location=124,
    release_string=128,                    # 48 bytes
)

# Descriptor layouts, as avb_hash_descriptor.h and avb_property_descriptor.h
# define them: a fixed header of big-endian fields, then the variable-length
# name/salt/digest (or key/value) bytes appended after it.
#   hash:     tag(8) length(8) image_size(8) algorithm(32) name_len(4)
#             salt_len(4) digest_len(4) flags(4) reserved(60) | name salt digest
#   property: tag(8) length(8) key_len(8) value_len(8)           | key value
DESCRIPTOR_HASH = 2
DESCRIPTOR_PROPERTY = 0
HASH_DESCRIPTOR_SIZE = 132
PROPERTY_DESCRIPTOR_SIZE = 32


def config(path: str | Path) -> dict:
    """Read configs/avb-vayu.json: per-partition size, salt and props."""
    return json.loads(Path(path).read_text())


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from(">Q", data, offset)[0]


def digest(image: bytes, salt: bytes) -> bytes:
    """The hash a hash-footer descriptor carries: SHA-256 over salt + image."""
    return hashlib.sha256(salt + image).digest()


def add_footer(image: Path, partition_name: str, partition_size: int,
               salt: str, props: list[str] | None = None,
               release_suffix: str | None = None) -> None:
    """Pad `image` to `partition_size` and append a hash footer, in place."""
    if not AVBTOOL.exists():
        raise SystemExit(f"missing {AVBTOOL}")
    data = Path(image).read_bytes()
    if len(data) > partition_size:
        raise SystemExit(f"{image} is {len(data):,} bytes, larger than the "
                         f"{partition_size:,}-byte partition")
    command = [sys.executable, str(AVBTOOL), "add_hash_footer",
               "--image", str(image),
               "--partition_name", partition_name,
               "--partition_size", str(partition_size),
               "--algorithm", "NONE",
               "--salt", salt]
    for prop in props or []:
        command += ["--prop", prop]
    if release_suffix is not None:
        command += ["--append_to_release_string", release_suffix]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"avbtool add_hash_footer failed:\n{result.stderr}")


def parse(path: Path | str | bytes) -> dict:
    """Read the footer, the vbmeta header and its descriptors.

    Accepts a path or the image bytes themselves: mkrelease.py has the payload
    out of the zip in memory and should not have to write it out to check it.
    """
    if isinstance(path, (bytes, bytearray)):
        data, label = bytes(path), "image"
    else:
        data, label = Path(path).read_bytes(), str(path)
    if len(data) < FOOTER_SIZE:
        raise ValueError(f"{label} is too small to hold an AVB footer")
    footer = data[-FOOTER_SIZE:]
    if footer[:4] != FOOTER_MAGIC:
        raise ValueError(f"{label} has no AVB footer (last bytes: "
                         f"{footer[:4]!r}, not {FOOTER_MAGIC!r})")
    info = {
        "size": len(data),
        "footer_version": (_u32(footer, 4), _u32(footer, 8)),
        "original_image_size": _u64(footer, 12),
        "vbmeta_offset": _u64(footer, 20),
        "vbmeta_size": _u64(footer, 28),
    }
    vb = data[info["vbmeta_offset"]:info["vbmeta_offset"] + info["vbmeta_size"]]
    if vb[:4] != VBMETA_MAGIC:
        raise ValueError(f"{label}: vbmeta at {info['vbmeta_offset']:,} is not "
                         f"an AVB0 blob (got {vb[:4]!r})")
    info.update({
        "vbmeta_version": (_u32(vb, 4), _u32(vb, 8)),
        "auth_block_size": _u64(vb, 12),
        "aux_block_size": _u64(vb, 20),
        "algorithm": _u32(vb, 28),
        "rollback_index": _u64(vb, 112),
        "flags": _u32(vb, 120),
        "rollback_index_location": _u32(vb, 124),
        "release_string": vb[128:176].split(b"\0")[0].decode(errors="replace"),
        "descriptors": [],
        "props": {},
    })
    # Descriptor offsets are relative to the auxiliary block, which starts
    # after the header and the authentication block (signed images have one).
    offset = HEADER_SIZE + info["auth_block_size"] + _u64(vb, 96)
    end = offset + _u64(vb, 104)
    while offset + 16 <= end:
        tag = _u64(vb, offset)
        length = _u64(vb, offset + 8)
        if length == 0:
            break
        if tag == DESCRIPTOR_HASH:
            image_size = _u64(vb, offset + 16)
            algorithm = vb[offset + 24:offset + 56].split(b"\0")[0].decode()
            name_len = _u32(vb, offset + 56)
            salt_len = _u32(vb, offset + 60)
            digest_len = _u32(vb, offset + 64)
            body = offset + HASH_DESCRIPTOR_SIZE
            name = vb[body:body + name_len]
            salt = vb[body + name_len:body + name_len + salt_len]
            desc_digest = vb[body + name_len + salt_len:
                             body + name_len + salt_len + digest_len]
            info["descriptors"].append({
                "image_size": image_size, "algorithm": algorithm,
                "salt": salt, "digest": desc_digest,
                "partition_name": name.split(b"\0")[0].decode(errors="replace"),
            })
        elif tag == DESCRIPTOR_PROPERTY:
            key_len = _u64(vb, offset + 16)
            value_len = _u64(vb, offset + 24)
            body = offset + PROPERTY_DESCRIPTOR_SIZE
            key = vb[body:body + key_len]
            value = vb[body + key_len:body + key_len + value_len]
            info["props"][key.split(b"\0")[0].decode(errors="replace")] = \
                value.split(b"\0")[0].decode(errors="replace")
        offset += 16 + length
    return info


def verify(path: Path, partition_name: str, partition_size: int,
           check=print) -> int:
    """Check that `path` is a footered image for this partition. Prints like
    the other scripts (ok/FAIL lines) and returns a count of failures."""
    failures = 0

    def check_(condition: bool, message: str) -> None:
        nonlocal failures
        if condition:
            check(f"ok   {message}")
        else:
            check(f"FAIL {message}")
            failures += 1

    data = Path(path).read_bytes()
    try:
        info = parse(path)
    except ValueError as error:
        check(f"FAIL {error}")
        return 1
    check_(len(data) == partition_size,
           f"image fills the {partition_size:,}-byte partition (got {len(data):,})")
    check_(info["footer_version"] == (1, 0),
           f"footer version is 1.0 (got {info['footer_version']})")
    check_(info["vbmeta_offset"] == info["original_image_size"],
           f"vbmeta follows the image ({info['vbmeta_offset']:,})")
    check_(info["algorithm"] == ALGORITHM_NONE,
           "vbmeta uses algorithm NONE, like the 5.4 image on this device")
    check_(info["auth_block_size"] == 0,
           f"no authentication block (got {info['auth_block_size']} bytes)")
    matching = [d for d in info["descriptors"]
                if d["partition_name"] == partition_name]
    check_(len(matching) == 1,
           f"exactly one hash descriptor names {partition_name} "
           f"(got {[d['partition_name'] for d in info['descriptors']]})")
    if matching:
        descriptor = matching[0]
        payload = data[:descriptor["image_size"]]
        check_(descriptor["image_size"] == info["original_image_size"],
               f"descriptor covers the whole image "
               f"({descriptor['image_size']:,} bytes)")
        actual = digest(payload, descriptor["salt"])
        check_(actual == descriptor["digest"],
               "sha256(salt + image) matches the descriptor "
               f"({actual.hex()[:16]}...)")
    padding = data[info["vbmeta_offset"] + info["vbmeta_size"]:-FOOTER_SIZE]
    check_(not any(padding),
           f"the {len(padding):,} bytes between vbmeta and footer are zero")
    return failures
