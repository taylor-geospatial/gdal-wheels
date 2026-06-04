# --- gdal-wheels runtime shim (prepended to osgeo/__init__.py at build time) ---
# Makes the self-contained wheel find its bundled GDAL/PROJ data and (on Windows)
# its vendored DLLs, since libgdal is built with an install prefix that does not
# exist on the end user's machine.
import os as _gw_os

# Keep os.add_dll_directory() handles alive for the life of the process. The
# handle returned by add_dll_directory() controls the registration's lifetime;
# dropping it can unregister the directory and cause intermittent Windows DLL
# load failures. Module-global storage pins them.
_gw_dll_dirs = []


def _gw_setup():
    _here = _gw_os.path.dirname(_gw_os.path.abspath(__file__))
    # Bundled data dirs (injected by ci/patch_wheel.py).
    _gdal_data = _gw_os.path.join(_here, "gdal_data")
    _proj_data = _gw_os.path.join(_here, "proj_data")
    # Default: only set GDAL_DATA/PROJ_DATA if not already set, so importing this
    # wheel does NOT clobber a co-installed rasterio/fiona/pyproj that set these
    # first (clobbering can cause cross-package proj.db schema mismatches). A user
    # who wants this wheel's bundled data to win can set GDAL_WHEELS_FORCE_DATA=1.
    _force = _gw_os.environ.get("GDAL_WHEELS_FORCE_DATA") == "1"

    def _set(var, val):
        if _force or not _gw_os.environ.get(var):
            _gw_os.environ[var] = val

    if _gw_os.path.isdir(_gdal_data):
        _set("GDAL_DATA", _gdal_data)
    if _gw_os.path.isdir(_proj_data):
        _set("PROJ_DATA", _proj_data)   # PROJ_DATA is current; PROJ_LIB is pre-9.1
        _set("PROJ_LIB", _proj_data)
    # Windows: register the vendored DLL directory that delvewheel created, and
    # keep the handle alive (see _gw_dll_dirs above).
    if _gw_os.name == "nt" and hasattr(_gw_os, "add_dll_directory"):
        _parent = _gw_os.path.dirname(_here)
        for _name in _gw_os.listdir(_parent):
            if _name.endswith(".libs"):
                _libdir = _gw_os.path.join(_parent, _name)
                if _gw_os.path.isdir(_libdir):
                    _gw_dll_dirs.append(_gw_os.add_dll_directory(_libdir))


_gw_setup()
del _gw_setup
# --- end gdal-wheels runtime shim ---
