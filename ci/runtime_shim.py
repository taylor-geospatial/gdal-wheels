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
    # Force the bundled paths so the wheel is genuinely self-contained: a stale
    # GDAL_DATA/PROJ_LIB pointing at a *different* (system) GDAL/PROJ would
    # otherwise win via setdefault and cause schema/CRS mismatches. Power users
    # who must override can set GDAL_WHEELS_RESPECT_ENV=1.
    _respect_env = _gw_os.environ.get("GDAL_WHEELS_RESPECT_ENV") == "1"
    if _gw_os.path.isdir(_gdal_data) and not (_respect_env and _gw_os.environ.get("GDAL_DATA")):
        _gw_os.environ["GDAL_DATA"] = _gdal_data
    if _gw_os.path.isdir(_proj_data):
        # PROJ_DATA is current; PROJ_LIB is the pre-9.1 name. Set both.
        if not (_respect_env and _gw_os.environ.get("PROJ_DATA")):
            _gw_os.environ["PROJ_DATA"] = _proj_data
        if not (_respect_env and _gw_os.environ.get("PROJ_LIB")):
            _gw_os.environ["PROJ_LIB"] = _proj_data
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
