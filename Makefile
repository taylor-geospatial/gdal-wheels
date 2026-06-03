# gdal-wheels local helpers.
#
# The full cross-platform build runs on GitHub Actions. Locally you can only
# iterate on the *Linux* build (in a manylinux container), which is enough to
# debug ci/build_gdal_hybrid.sh and the vcpkg dependency set.

GDAL_VERSION ?= 3.13.0
# Build all CPython 3.12-3.14 by default; override e.g. PYTHON=cp312-cp312
PYTHON ?=

.PHONY: help fetch lint linux clean

help:
	@echo "make fetch    - download GDAL $(GDAL_VERSION) sdist -> gdal-src/ (renamed)"
	@echo "make lint     - shell + python syntax check the build scripts"
	@echo "make linux    - build Linux wheels locally via cibuildwheel (needs Docker/Podman)"
	@echo "make clean    - remove build artifacts"

fetch:
	bash ci/fetch_gdal_src.sh $(GDAL_VERSION)

lint:
	bash -n ci/fetch_gdal_src.sh ci/build_gdal_hybrid.sh ci/build_gdal_windows.sh
	python -m py_compile ci/patch_wheel.py ci/runtime_shim.py tests/test_smoke.py tests/test_functional.py
	@command -v shellcheck >/dev/null 2>&1 && shellcheck ci/fetch_gdal_src.sh ci/build_gdal_hybrid.sh || echo "(shellcheck not installed, skipped)"

# Local Linux-only build. Reads the same CIBW_* settings as CI from the env;
# here we set the minimum needed to reproduce the hybrid manylinux build.
linux: fetch
	GDAL_VERSION=$(GDAL_VERSION) \
	CIBW_BUILD="$(PYTHON)" \
	CIBW_ENABLE=cpython-freethreading \
	CIBW_SKIP='*pp* *musllinux*' \
	CIBW_ENVIRONMENT_LINUX="GDAL_VERSION=$(GDAL_VERSION) BUILD_PREFIX=/opt/gdaldeps PATH=/opt/gdaldeps/bin:\$$PATH LD_LIBRARY_PATH=/opt/gdaldeps/lib:/opt/gdaldeps/lib64:\$$LD_LIBRARY_PATH" \
	CIBW_BEFORE_ALL_LINUX="bash ./ci/build_gdal_hybrid.sh \$$GDAL_VERSION /opt/gdaldeps" \
	CIBW_REPAIR_WHEEL_COMMAND_LINUX="export 'LD_LIBRARY_PATH=/opt/gdaldeps/lib64:/opt/gdaldeps/lib:\$$LD_LIBRARY_PATH' && rm -rf /tmp/repaired && mkdir -p /tmp/repaired && auditwheel repair -w /tmp/repaired {wheel} && python {project}/ci/patch_wheel.py '/tmp/repaired/*.whl' {dest_dir} --gdal-data /opt/gdaldeps/share/gdal --proj-data /opt/gdaldeps/share/proj --licenses-src /opt/gdaldeps" \
	CIBW_TEST_REQUIRES="numpy pytest" \
	CIBW_TEST_COMMAND="python {project}/tests/test_smoke.py && python -m pytest {project}/tests/test_functional.py -v" \
	python -m cibuildwheel --platform linux --output-dir wheelhouse gdal-src

clean:
	rm -rf gdal-src _gdal_sdist gdal_libs vcpkg wheelhouse dist build
