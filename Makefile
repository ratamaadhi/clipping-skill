.PHONY: help test lint clean demo

PY ?= python3

help:
	@echo "make test    - jalankan tes offline (tanpa video, tanpa API key)"
	@echo "make lint    - py_compile semua modul"
	@echo "make demo    - jalankan pipeline pada fixture sintetis"
	@echo "make clean   - hapus work/ dan __pycache__"

test:
	@$(PY) -m pytest -q 2>/dev/null || $(PY) -m unittest discover -s tests -v

lint:
	@$(PY) -m compileall -q scripts tests && echo "compile OK"

demo:
	@$(PY) -m scripts.cli demo --out work/demo

clean:
	@rm -rf work .pytest_cache
	@find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "bersih"
