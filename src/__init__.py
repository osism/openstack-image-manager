__all__ = ['__version__']

import pbr.version

version_info = pbr.version.VersionInfo('openstack-image-manager')
# We have a circular import problem when we first run python setup.py sdist
# It's harmless, so deflect it.
try:
    __version__ = version_info.version_string()
except AttributeError:
    __version__ = None
