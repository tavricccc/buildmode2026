"""Care Agent v4 backend package.

This package implements the v4 specification (see
``docs-implementation-v4/``) in a hardware-neutral way: domain code does not
import ``mlx``, ``mps``, ``cuda``, ``rocm``, ``torch`` or any Apple/Metal
specific module. Hardware differences are confined to ``adapters/`` and
``supervisor/``.

The package is intentionally a single distribution: v3 is not imported.
The legacy ``capture/`` package at the repo root is a separate CLI used
during host bootstrap.
"""

__version__ = "0.1.0"
