# SPDX-License-Identifier: Apache-2.0

__all__ = ["__version__"]

try:
    from importlib.metadata import version, PackageNotFoundError  # type: ignore[attr-defined]
except ImportError:
    from importlib_metadata import version, PackageNotFoundError  # type: ignore[import,no-redef]

try:
    __version__ = version(__name__)
except PackageNotFoundError:
    __version__ = ""
