# SPDX-License-Identifier: Apache-2.0

__all__ = ["__version__"]

from pkg_resources import get_distribution, DistributionNotFound

try:
    __version__ = get_distribution(__name__).version
except DistributionNotFound:
    __version__ = ""
