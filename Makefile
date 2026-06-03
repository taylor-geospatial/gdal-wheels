# gdal-wheels local helpers.
#
# The full cross-platform build runs on GitHub Actions. Locally you can only
# iterate on the *Linux* build (in a manylinux container), which is enough to
# debug ci/config.sh and the dependency chain.

GDAL_VERSION ?= 3.13.0
# Build all CPython 3.12-3.14 by default; override e.g. PYTHON=cp312-cp312
PYTHON ?=

.PHONY: help fetch lint linux clean

help:
	@echo "make fetch    - download GDAL $(GDAL_VERSION) sdist -> gdal-src/ (renamed)"
	@echo "make lint     - shellcheck + python syntax check the build scripts"
	@echo "make linux    - build Linux wheels locally via cibuildwheel (needs Docker/Podman)"
	@echo "make clean     - remove build artifacts"

fetch:
	bash ci/fetch_gdal_src.sh $(GDAL_VERSION)

lint:
	bash -n ci/fetch_gdal_src.sh ci/config.sh
	python -m py_compile ci/patch_wheel.py ci/runtime_shim.py tests/test_smoke.py
	@command -v shellcheck >/dev/null 2>&1 && shellcheck ci/fetch_gdal_src.sh || echo "(shellcheck not installed, skipped)"

# Local Linux-only build. Reads the same CIBW_* settings as CI from the env;
# here we set the minimum needed to reproduce the manylinux build.
linux: fetch
	GDAL_VERSION=$(GDAL_VERSION) \
	CIBW_BUILD="$(PYTHON)" \
	CIBW_ENABLE=cpython-freethreading \
	CIBW_SKIP='*pp* *musllinux*' \
	CIBW_ENVIRONMENT_LINUX="GDAL_VERSION=$(GDAL_VERSION) BUILD_PREFIX=/usr/local" \
	CIBW_BEFORE_ALL_LINUX="yum install -y wget cmake perl-core zlib-devel bzip2 && bash ./ci/config.sh" \
	CIBW_REPAIR_WHEEL_COMMAND_LINUX="export 'LD_LIBRARY_PATH=/usr/local/lib64:/usr/local/lib:\$$LD_LIBRARY_PATH' && auditwheel repair -w /tmp/repaired {wheel} && python {project}/ci/patch_wheel.py '/tmp/repaired/*.whl' {dest_dir} --gdal-data /usr/local/share/gdal --proj-data /usr/local/share/proj" \
	CIBW_TEST_REQUIRES=numpy \
	CIBW_TEST_COMMAND="python {project}/tests/test_smoke.py" \
	python -m cibuildwheel --platform linux --output-dir wheelhouse gdal-src

clean:
	rm -rf gdal-src _gdal_sdist gdal_libs wheelhouse dist build
