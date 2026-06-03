#!/usr/bin/env python3
"""Smoke test for a freshly built gdal-wheels wheel.

Run by cibuildwheel (CIBW_TEST_COMMAND) against the *installed* wheel, so it
verifies the wheel is self-contained: extensions import, libgdal loads, the
bundled GDAL_DATA/PROJ_DATA resolve, and numpy array support is present.

Exits non-zero on any failure so a broken wheel never ships.
"""

import os
import sys


def main():
    from osgeo import gdal, ogr, osr

    gdal.UseExceptions()
    print(f"GDAL version: {gdal.__version__}  (lib {gdal.VersionInfo('RELEASE_NAME')})")

    # 1. GDAL_DATA must resolve (bundled). gdalvrt.xsd lives in the data dir.
    gdal_data = gdal.GetConfigOption("GDAL_DATA")
    print(f"GDAL_DATA = {gdal_data}")
    assert gdal_data, "GDAL_DATA not set — bundled data dir not found"

    # 2. A raster driver must be available and creatable in memory.
    drv = gdal.GetDriverByName("GTiff")
    assert drv is not None, "GTiff driver missing"
    ds = gdal.GetDriverByName("MEM").Create("", 16, 16, 1, gdal.GDT_Byte)
    assert ds is not None and ds.RasterXSize == 16
    print(f"raster drivers registered: {gdal.GetDriverCount()}")

    # 3. PROJ must work (needs proj.db from the bundled PROJ_DATA).
    srs = osr.SpatialReference()
    assert srs.ImportFromEPSG(4326) == 0, "could not import EPSG:4326 — PROJ data missing"
    srs_utm = osr.SpatialReference()
    srs_utm.ImportFromEPSG(32616)
    ct = osr.CoordinateTransformation(srs, srs_utm)
    x, y, _ = ct.TransformPoint(29.0, -98.0)
    print(f"PROJ transform 4326->32616 ok: ({x:.1f}, {y:.1f})")

    # 4. A vector driver round-trips in memory.
    vdrv = ogr.GetDriverByName("Memory")
    src = vdrv.CreateDataSource("mem")
    assert src is not None
    print(f"vector drivers registered: {ogr.GetDriverCount()}")

    # 4b. The expanded driver set must be present (registration, not connection).
    expected = ["GeoJSON", "GML", "CSV", "KML", "FlatGeobuf", "MVT",  # vector optional
                "PostgreSQL", "Parquet", "Arrow",                     # libpq, arrow
                "Zarr"]                                               # raster
    missing = [d for d in expected if gdal.GetDriverByName(d) is None
               and ogr.GetDriverByName(d) is None]
    present = [d for d in expected if d not in missing]
    print(f"expected drivers present: {present}")
    assert not missing, f"expected drivers missing from wheel: {missing}"

    # 5. numpy array support (the gdal_array extension) must be built in.
    from osgeo import gdal_array
    import numpy as np

    arr = np.arange(256, dtype="uint8").reshape(16, 16)
    mem = gdal_array.OpenArray(arr)
    assert mem is not None
    out = mem.ReadAsArray()
    assert (out == arr).all(), "gdal_array round-trip mismatch"
    print("gdal_array numpy round-trip ok")

    # 6. Bundled dependency licenses must be present (compliance).
    import osgeo as _osgeo
    licdir = os.path.join(os.path.dirname(_osgeo.__file__), "licenses")
    lics = os.listdir(licdir) if os.path.isdir(licdir) else []
    print(f"bundled dependency licenses: {len(lics)}")
    assert len(lics) >= 5, f"expected bundled dep licenses in osgeo/licenses, found {lics}"

    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # smoke test: any failure must fail the build loudly
        print(f"SMOKE TEST FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
