#!/usr/bin/env python3
"""Functional correctness tests for the gdal-wheels wheels.

Unlike a smoke test ("does it import?"), these assert that GDAL actually
*computes correctly* through the vendored stack: raster I/O round-trips bit for
bit, reprojection matches known reference coordinates, GEOS geometry ops are
numerically right, and the bundled format drivers (Parquet/Arrow/Zarr) truly
read back what they wrote. Run against the installed wheel in CI (every
platform x Python), so a driver that silently returns wrong data fails the build.

Self-contained: all inputs are generated in-process; no external data/network.
"""
import math

import numpy as np
import pytest
from osgeo import gdal, ogr, osr, gdal_array

gdal.UseExceptions()
ogr.UseExceptions()


def _srs(epsg):
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)  # predictable (x, y)
    return s


# --------------------------------------------------------------------------
# Raster I/O round-trips
# --------------------------------------------------------------------------

@pytest.mark.parametrize("gdt,npdt", [
    (gdal.GDT_Byte, np.uint8),
    (gdal.GDT_Int16, np.int16),
    (gdal.GDT_UInt16, np.uint16),
    (gdal.GDT_Int32, np.int32),
    (gdal.GDT_Float32, np.float32),
    (gdal.GDT_Float64, np.float64),
])
def test_geotiff_roundtrip_preserves_pixels_and_dtype(tmp_path, gdt, npdt):
    path = str(tmp_path / "r.tif")
    data = (np.arange(64, dtype=npdt).reshape(8, 8))
    ds = gdal.GetDriverByName("GTiff").Create(path, 8, 8, 1, gdt)
    ds.GetRasterBand(1).WriteArray(data)
    ds = None

    ds = gdal.Open(path)
    out = ds.GetRasterBand(1).ReadAsArray()
    assert out.dtype == npdt
    assert np.array_equal(out, data), "pixel values not preserved"
    ds = None


def test_geotiff_preserves_geotransform_crs_nodata(tmp_path):
    path = str(tmp_path / "geo.tif")
    gt = (440720.0, 60.0, 0.0, 3751320.0, 0.0, -60.0)
    ds = gdal.GetDriverByName("GTiff").Create(path, 4, 4, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    ds.SetProjection(_srs(32611).ExportToWkt())
    ds.GetRasterBand(1).SetNoDataValue(-9999.0)
    ds.GetRasterBand(1).WriteArray(np.full((4, 4), 1.5, np.float32))
    ds = None

    ds = gdal.Open(path)
    assert ds.GetGeoTransform() == pytest.approx(gt)
    assert ds.GetRasterBand(1).GetNoDataValue() == pytest.approx(-9999.0)
    got = osr.SpatialReference(ds.GetProjection())
    assert got.GetAuthorityCode(None) == "32611"
    ds = None


def test_multiband_roundtrip(tmp_path):
    path = str(tmp_path / "rgb.tif")
    bands = [np.full((5, 5), v, np.uint8) for v in (10, 20, 30)]
    ds = gdal.GetDriverByName("GTiff").Create(path, 5, 5, 3, gdal.GDT_Byte)
    for i, b in enumerate(bands, 1):
        ds.GetRasterBand(i).WriteArray(b)
    ds = None
    ds = gdal.Open(path)
    assert ds.RasterCount == 3
    for i, b in enumerate(bands, 1):
        assert np.array_equal(ds.GetRasterBand(i).ReadAsArray(), b)
    ds = None


def test_overviews_decimate(tmp_path):
    path = str(tmp_path / "ov.tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, 64, 64, 1, gdal.GDT_Byte)
    ds.GetRasterBand(1).WriteArray(np.random.randint(0, 255, (64, 64)).astype(np.uint8))
    ds.BuildOverviews("AVERAGE", [2, 4])
    assert ds.GetRasterBand(1).GetOverviewCount() == 2
    assert ds.GetRasterBand(1).GetOverview(0).XSize == 32
    ds = None


# --------------------------------------------------------------------------
# Reprojection / PROJ correctness (numeric reference values)
# --------------------------------------------------------------------------

def test_transform_4326_to_3857_known_value():
    ct = osr.CoordinateTransformation(_srs(4326), _srs(3857))
    x, y, _ = ct.TransformPoint(2.0, 49.0)  # lon, lat
    # Authoritative WebMercator value for (2E, 49N):
    assert x == pytest.approx(222638.9816, abs=1e-2)
    assert y == pytest.approx(6274861.3944, abs=1e-2)


def test_transform_roundtrip_identity():
    fwd = osr.CoordinateTransformation(_srs(4326), _srs(32633))
    inv = osr.CoordinateTransformation(_srs(32633), _srs(4326))
    x, y, _ = fwd.TransformPoint(15.0, 47.0)
    lon, lat, _ = inv.TransformPoint(x, y)
    assert lon == pytest.approx(15.0, abs=1e-7)
    assert lat == pytest.approx(47.0, abs=1e-7)


def test_proj_db_present_epsg_lookups():
    # Needs a working proj.db (the bundled PROJ_DATA).
    for epsg, auth in [(4326, "WGS 84"), (3857, "Pseudo-Mercator"), (32633, "WGS 84")]:
        s = osr.SpatialReference()
        s.ImportFromEPSG(epsg)
        assert auth.split()[0] in s.GetName()


def test_warp_reprojects_raster(tmp_path):
    src = str(tmp_path / "src.tif")
    ds = gdal.GetDriverByName("GTiff").Create(src, 16, 16, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((10.0, 0.01, 0, 47.0, 0, -0.01))
    ds.SetProjection(_srs(4326).ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.full((16, 16), 42, np.uint8))
    ds = None
    out = gdal.Warp(str(tmp_path / "out.tif"), src, dstSRS="EPSG:3857")
    assert out is not None and out.RasterXSize > 0
    assert osr.SpatialReference(out.GetProjection()).GetAuthorityCode(None) == "3857"
    out = None


# --------------------------------------------------------------------------
# GEOS-backed geometry correctness
# --------------------------------------------------------------------------

def test_geos_buffer_area():
    g = ogr.CreateGeometryFromWkt("POINT (0 0)")
    buf = g.Buffer(1.0, 64)  # high segment count -> close to a true circle
    assert buf.GetArea() == pytest.approx(math.pi, abs=1e-2)


def test_geos_intersection_union():
    a = ogr.CreateGeometryFromWkt("POLYGON ((0 0,0 2,2 2,2 0,0 0))")
    b = ogr.CreateGeometryFromWkt("POLYGON ((1 1,1 3,3 3,3 1,1 1))")
    assert a.Intersection(b).GetArea() == pytest.approx(1.0, abs=1e-9)
    assert a.Union(b).GetArea() == pytest.approx(7.0, abs=1e-9)
    assert a.Intersects(b) is True


def test_geos_validity_and_distance():
    a = ogr.CreateGeometryFromWkt("POINT (0 0)")
    b = ogr.CreateGeometryFromWkt("POINT (3 4)")
    assert a.Distance(b) == pytest.approx(5.0, abs=1e-9)
    assert ogr.CreateGeometryFromWkt("POLYGON ((0 0,0 1,1 1,1 0,0 0))").IsValid()


# --------------------------------------------------------------------------
# Vector format round-trips (incl. the expanded drivers)
# --------------------------------------------------------------------------

def _write_points(path, driver):
    ds = ogr.GetDriverByName(driver).CreateDataSource(path)
    srs = _srs(4326)
    lyr = ds.CreateLayer("pts", srs=srs, geom_type=ogr.wkbPoint)
    lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    lyr.CreateField(ogr.FieldDefn("val", ogr.OFTInteger))
    for i, (x, y) in enumerate([(1.0, 2.0), (3.5, -4.25), (10.0, 20.0)]):
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(ogr.CreateGeometryFromWkt(f"POINT ({x} {y})"))
        f.SetField("name", f"p{i}")
        f.SetField("val", i * 100)
        lyr.CreateFeature(f)
    ds = None


def _read_points(path):
    ds = ogr.Open(path)
    lyr = ds.GetLayer(0)
    out = []
    for f in lyr:
        g = f.GetGeometryRef()
        out.append((f.GetField("name"), f.GetField("val"), round(g.GetX(), 6), round(g.GetY(), 6)))
    return sorted(out)


EXPECTED_POINTS = sorted([("p0", 0, 1.0, 2.0), ("p1", 100, 3.5, -4.25), ("p2", 200, 10.0, 20.0)])


@pytest.mark.parametrize("driver,ext", [
    ("GeoJSON", "geojson"),
    ("GPKG", "gpkg"),
    ("FlatGeobuf", "fgb"),
    ("ESRI Shapefile", "shp"),
    ("Parquet", "parquet"),   # the headline new driver
    ("Arrow", "arrow"),
])
def test_vector_roundtrip(tmp_path, driver, ext):
    if ogr.GetDriverByName(driver) is None:
        pytest.skip(f"{driver} driver not available")
    path = str(tmp_path / f"v.{ext}")
    _write_points(path, driver)
    assert _read_points(path) == EXPECTED_POINTS, f"{driver} round-trip mismatch"


def test_attribute_and_spatial_filter(tmp_path):
    path = str(tmp_path / "f.gpkg")
    _write_points(path, "GPKG")
    ds = ogr.Open(path)
    lyr = ds.GetLayer(0)
    lyr.SetAttributeFilter("val >= 100")
    assert lyr.GetFeatureCount() == 2
    lyr.SetAttributeFilter(None)
    lyr.SetSpatialFilterRect(0.0, 0.0, 5.0, 5.0)
    assert lyr.GetFeatureCount() == 1  # only (1,2) lies in the box
    ds = None


# --------------------------------------------------------------------------
# Zarr (multidim raster) round-trip
# --------------------------------------------------------------------------

def test_zarr_roundtrip(tmp_path):
    if gdal.GetDriverByName("Zarr") is None:
        pytest.skip("Zarr driver not available")
    path = str(tmp_path / "z.zarr")
    data = np.arange(100, dtype=np.float32).reshape(10, 10)
    mem = gdal.GetDriverByName("MEM").Create("", 10, 10, 1, gdal.GDT_Float32)
    mem.GetRasterBand(1).WriteArray(data)
    gdal.GetDriverByName("Zarr").CreateCopy(path, mem)
    mem = None
    ds = gdal.Open(path)
    assert np.array_equal(ds.GetRasterBand(1).ReadAsArray(), data)
    ds = None


# --------------------------------------------------------------------------
# numpy <-> GDAL (gdal_array) correctness
# --------------------------------------------------------------------------

def test_gdal_array_roundtrip_multiband():
    arr = np.stack([
        np.arange(16, dtype=np.float32).reshape(4, 4),
        np.arange(16, 32, dtype=np.float32).reshape(4, 4),
    ])
    ds = gdal_array.OpenArray(arr)
    out = ds.ReadAsArray()
    assert out.shape == arr.shape
    assert np.array_equal(out, arr)


def test_vsimem_in_memory_io():
    path = "/vsimem/mem.tif"
    ds = gdal.GetDriverByName("GTiff").Create(path, 3, 3, 1, gdal.GDT_Byte)
    ds.GetRasterBand(1).WriteArray(np.full((3, 3), 7, np.uint8))
    ds = None
    ds = gdal.Open(path)
    assert int(ds.GetRasterBand(1).ReadAsArray().mean()) == 7
    ds = None
    gdal.Unlink(path)


# --------------------------------------------------------------------------
# Error propagation
# --------------------------------------------------------------------------

def test_open_missing_raises():
    with pytest.raises(RuntimeError):
        gdal.Open("/nonexistent/definitely-not-here.tif")
