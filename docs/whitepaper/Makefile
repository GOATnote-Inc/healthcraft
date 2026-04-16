# ============================================================
# Whitepaper Build System (CI-Hardened)
# ============================================================
# Produces two PDFs from single source:
#   - output/whitepaper_named.pdf     (public release)
#   - output/whitepaper_anonymous.pdf (blind review)
#
# Aligned with:
#   - NeurIPS 2026 Datasets & Benchmarks Track submission
#   - arXiv preprint requirements
#   - GitHub Actions CI compatibility
#
# Usage:
#   make all        # Build both versions
#   make named      # Build named version only
#   make anonymous  # Build anonymous version only
#   make verify     # Verify builds are correct
#   make clean      # Remove build artifacts
#   make ci         # Full CI pipeline (clean + all + verify)
# ============================================================

# Tools (override for CI if needed)
PDFLATEX ?= pdflatex
BIBTEX ?= bibtex

# Directories
OUT = output
SRC = .

# CI-safe flags (no interactive prompts, fail fast)
PDFLATEX_FLAGS = -interaction=nonstopmode -halt-on-error -file-line-error
RM = rm -f

# Expected outputs
NAMED_PDF = $(OUT)/whitepaper_named.pdf
ANON_PDF = $(OUT)/whitepaper_anonymous.pdf

# ============================================================
# Main targets
# ============================================================

.PHONY: all named anonymous clean distclean verify ci setup help arxiv

all: named anonymous
	@echo ""
	@echo "============================================================"
	@echo "Build complete"
	@echo "   Named:     $(NAMED_PDF)"
	@echo "   Anonymous: $(ANON_PDF)"
	@echo "============================================================"

# ============================================================
# Setup
# ============================================================

setup:
	@mkdir -p $(OUT)

# ============================================================
# Named build (public release)
# ============================================================

named: setup
	@echo "Building named version..."
	@$(PDFLATEX) $(PDFLATEX_FLAGS) -output-directory=$(OUT) build_named.tex > /dev/null
	@-cp references.bib $(OUT)/ 2>/dev/null || true
	@-cd $(OUT) && BIBINPUTS=".:.." $(BIBTEX) build_named > /dev/null 2>&1 || true
	@$(PDFLATEX) $(PDFLATEX_FLAGS) -output-directory=$(OUT) build_named.tex > /dev/null
	@$(PDFLATEX) $(PDFLATEX_FLAGS) -output-directory=$(OUT) build_named.tex > /dev/null
	@cp $(OUT)/build_named.pdf $(NAMED_PDF)
	@echo "Wrote $(NAMED_PDF)"

# ============================================================
# Anonymous build (blind review)
# ============================================================

anonymous: setup
	@echo "Building anonymous version..."
	@$(PDFLATEX) $(PDFLATEX_FLAGS) -output-directory=$(OUT) build_anonymous.tex > /dev/null
	@-cp references.bib $(OUT)/ 2>/dev/null || true
	@-cd $(OUT) && BIBINPUTS=".:.." $(BIBTEX) build_anonymous > /dev/null 2>&1 || true
	@$(PDFLATEX) $(PDFLATEX_FLAGS) -output-directory=$(OUT) build_anonymous.tex > /dev/null
	@$(PDFLATEX) $(PDFLATEX_FLAGS) -output-directory=$(OUT) build_anonymous.tex > /dev/null
	@cp $(OUT)/build_anonymous.pdf $(ANON_PDF)
	@echo "Wrote $(ANON_PDF)"

# ============================================================
# Verification (CI gate)
# ============================================================

verify:
	@echo ""
	@echo "Verifying builds..."
	@echo "------------------------------------------------------------"
	@# Check files exist
	@test -f $(NAMED_PDF) || (echo "FAIL: $(NAMED_PDF) not found" && exit 1)
	@test -f $(ANON_PDF) || (echo "FAIL: $(ANON_PDF) not found" && exit 1)
	@echo "PASS: Both PDFs exist"
	@# Check files are valid PDFs (have PDF header)
	@head -c 5 $(NAMED_PDF) | grep -q '%PDF' || (echo "FAIL: $(NAMED_PDF) is not a valid PDF" && exit 1)
	@head -c 5 $(ANON_PDF) | grep -q '%PDF' || (echo "FAIL: $(ANON_PDF) is not a valid PDF" && exit 1)
	@echo "PASS: Both PDFs have valid headers"
	@# Check minimum file size (should be > 100KB for a real paper)
	@test $$(stat -f%z $(NAMED_PDF) 2>/dev/null || stat -c%s $(NAMED_PDF)) -gt 100000 || (echo "FAIL: $(NAMED_PDF) too small" && exit 1)
	@test $$(stat -f%z $(ANON_PDF) 2>/dev/null || stat -c%s $(ANON_PDF)) -gt 100000 || (echo "FAIL: $(ANON_PDF) too small" && exit 1)
	@echo "PASS: Both PDFs have valid size (>100KB)"
	@# Content verification (requires pdftotext from poppler-utils)
	@if command -v pdftotext >/dev/null 2>&1; then \
		if ! pdftotext $(NAMED_PDF) - 2>/dev/null | grep -q "b@thegoatnote.com"; then echo "FAIL: Named PDF missing author email"; exit 1; fi; \
		if pdftotext $(ANON_PDF) - 2>/dev/null | grep -q "b@thegoatnote.com"; then echo "FAIL: Anonymous PDF contains author email (identity leak)"; exit 1; fi; \
		if pdftotext $(ANON_PDF) - 2>/dev/null | grep -qi "Brandon"; then echo "FAIL: Anonymous PDF contains author name (identity leak)"; exit 1; fi; \
		if pdftotext $(ANON_PDF) - 2>/dev/null | grep -q "GOATnote"; then echo "FAIL: Anonymous PDF contains affiliation (identity leak)"; exit 1; fi; \
		echo "PASS: Content verification (pdftotext)"; \
	else \
		echo "WARN: pdftotext not found - skipping content verification"; \
		echo "   Install with: brew install poppler (macOS) or apt install poppler-utils (Linux)"; \
	fi
	@# Canonical numbers audit (if verify script present)
	@if [ -f ../../scripts/verify_canonical_numbers.py ]; then \
		python3 ../../scripts/verify_canonical_numbers.py || (echo "FAIL: canonical numbers mismatch" && exit 1); \
		echo "PASS: Canonical numbers audit"; \
	else \
		echo "WARN: scripts/verify_canonical_numbers.py not found - skipping audit"; \
	fi
	@echo "------------------------------------------------------------"
	@echo "PASS: All verification checks passed"

# ============================================================
# CI pipeline (full build + verify)
# ============================================================

ci: clean all verify
	@echo ""
	@echo "============================================================"
	@echo "CI pipeline complete"
	@echo "============================================================"

# ============================================================
# Cleanup (CI-safe, no interactive prompts)
# ============================================================

clean:
	@echo "Cleaning build artifacts..."
	@$(RM) $(OUT)/*.aux $(OUT)/*.log $(OUT)/*.out $(OUT)/*.bbl $(OUT)/*.blg $(OUT)/*.toc 2>/dev/null || true
	@echo "Cleaned"

distclean: clean
	@echo "Removing all PDFs..."
	@$(RM) $(OUT)/*.pdf 2>/dev/null || true
	@echo "All PDFs removed"

# ============================================================
# arXiv submission helper
# ============================================================

arxiv: named
	@echo ""
	@echo "Preparing arXiv submission..."
	@mkdir -p arxiv_submission
	@cp content.tex arxiv_submission/
	@cp appendix.tex arxiv_submission/
	@cp metadata.tex arxiv_submission/
	@cp build_named.tex arxiv_submission/ms.tex
	@cp references.bib arxiv_submission/ 2>/dev/null || true
	@cp -r figures arxiv_submission/ 2>/dev/null || true
	@cp -r sty arxiv_submission/ 2>/dev/null || true
	@echo "arXiv submission prepared in arxiv_submission/"
	@echo "   Upload arxiv_submission/ directory to arXiv"

# ============================================================
# Help
# ============================================================

help:
	@echo "Whitepaper Build System"
	@echo ""
	@echo "Targets:"
	@echo "  make all        Build both named and anonymous PDFs"
	@echo "  make named      Build named version (public release)"
	@echo "  make anonymous  Build anonymous version (blind review)"
	@echo "  make verify     Verify builds are correct (CI gate)"
	@echo "  make ci         Full CI pipeline (clean + all + verify)"
	@echo "  make clean      Remove build artifacts"
	@echo "  make distclean  Remove all PDFs"
	@echo "  make arxiv      Prepare arXiv submission package"
	@echo "  make help       Show this help"
