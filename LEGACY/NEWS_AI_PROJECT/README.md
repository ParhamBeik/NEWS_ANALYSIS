# Iranian News Pipeline Project

Automated news monitoring system for Iranian news sources with AI-powered classification and evaluation.

## Quick Start

### Run Production Pipeline
```bash
python3 news_pipeline_single_run.py
```

### Run Test Pipeline (with improvements)
```bash
python3 news_pipeline_test_version.py
```

## Documentation

📚 **Complete documentation available in [`CLAUDE MARKDOWN/`](CLAUDE%20MARKDOWN/) folder**

Start here: [`CLAUDE MARKDOWN/00_README.md`](CLAUDE%20MARKDOWN/00_README.md)

### Quick Links
- [Project Overview](CLAUDE%20MARKDOWN/01_PROJECT_OVERVIEW.md) - Complete project summary
- [Improvements](CLAUDE%20MARKDOWN/02_IMPROVEMENTS_IMPLEMENTED.md) - What's new and improved
- [Bug Fix Details](CLAUDE%20MARKDOWN/03_BUG_FIX_DETAILS.md) - Recent bug fix explained
- [Testing Guide](CLAUDE%20MARKDOWN/04_TESTING_GUIDE.md) - How to test and compare

## Project Structure

```
NEWS_AI_PROJECT/
├── خبر فوری/              # Production outputs
├── TEST_OUTPUT/           # Test outputs (new improvements)
├── news_pipeline_single_run.py      # Production pipeline
├── news_pipeline_test_version.py    # Test pipeline (improved)
├── prompt_improvements.py           # New AI prompts
└── CLAUDE MARKDOWN/                 # Documentation
```

## Current Status

- ✅ Production pipeline working
- ✅ Test pipeline bug fixed
- ✅ File structure updated
- ✅ Documentation consolidated
- ⏳ Ready for testing

## Key Features

### Production Pipeline
- Generic evaluation for all categories
- Outputs to `خبر فوری/`
- Proven and stable

### Test Pipeline (Improvements)
- Category-specific AI expert personas
- 30-day memory window (reduces bias)
- Automatic TXT file generation
- 49% API cost savings
- Outputs to `TEST_OUTPUT/`

## Next Steps

1. Read documentation: `cat "CLAUDE MARKDOWN/00_README.md"`
2. Run test pipeline: `python3 news_pipeline_test_version.py`
3. Compare outputs: Production vs Test
4. Follow testing guide for detailed comparison

## Recent Changes (April 23, 2026)

- Moved TEST_OUTPUT to project root (cleaner structure)
- Updated all code references
- Consolidated documentation into organized folder
- Fixed validation bug in test pipeline

See [`CLAUDE MARKDOWN/CHANGES_SUMMARY.md`](CLAUDE%20MARKDOWN/CHANGES_SUMMARY.md) for details.

---

**Documentation created by:** Claude (Anthropic AI Assistant)  
**Last updated:** April 23, 2026
