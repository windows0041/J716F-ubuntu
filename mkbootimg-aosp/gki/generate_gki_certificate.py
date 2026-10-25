"""Stub for GKI boot signature generation.

The real implementation lives in AOSP and requires avbtool. We only use
mkbootimg to assemble a header v2 image (no GKI signing), so this stub is
never invoked in practice -- it exists solely to satisfy the import.
"""


def generate_gki_certificate(image, avbtool, name, algorithm, key, salt,
                             additional_avb_args, **kwargs):
    raise NotImplementedError(
        "GKI boot signing is not available in this trimmed-down mkbootimg. "
        "Do not pass --gki_signing_key / --gki_signing_algorithm."
    )
