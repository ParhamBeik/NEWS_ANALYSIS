# News Pipeline Project - Complete Overview

**Last Updated:** April 23, 2026  
**Status:** Test version bug fixed, ready for testing

## Project Summary

This is an automated Iranian news monitoring system that fetches, classifies, evaluates, and organizes news articles from khabarfoori.com with AI-powered analysis.

### Core Functionality
1. **Fetch** - Scrapes news from khabarfoori.com every minute
2. **Classify** - Categorizes into security, economics, security/economics, or other
3. **Evaluate** - Uses category-specific AI expert personas to assess importance
4. **Organize** - Generates Excel reports, TXT files, and notifications
5. **Track** - Maintains historical database and API cost tracking

## Project Structure

```
NEWS_AI_PROJECT/
├── data/                              # News fetching scripts & raw data
│   └── [various news sources]
│
├── خبر فوری/                          # PRODUCTION outputs
│   ├── JSON Files/
│   │   ├── news_database.json        # Main database (5503 articles)
│   │   ├── api_costs.json            # Cost tracking
│   │   └── prompt_memory.json        # Classification memory
│   ├── Excel Files/                  # Daily Excel reports
│   ├── LOG Files/                    # Execution logs
│   ├── Markdown Files/               # Classification rubric & memory
│   ├── TXT Files/                    # Category-specific outputs
│   └── important_news.txt            # Notified articles (11,005 lines)
│
├── TEST_OUTPUT/                       # TEST version outputs (NEW LOCATION)
│   ├── JSON Files/
│   ├── Excel Files/
│   ├── LOG Files/
│   ├── Markdown Files/
│   ├── TXT Files/
│   └── important_news.txt
│
├── news_pipeline_single_run.py       # Production pipeline (OLD prompts)
├── news_pipeline_test_version.py     # Test pipeline (NEW prompts, bug fixed)
├── news_pipeline_scheduled_loop.py   # Looped version
├── prompt_improvements.py            # New prompt templates
│
└── CLAUDE MARKDOWN/                   # Documentation folder
    ├── 01_PROJECT_OVERVIEW.md        # This file
    ├── 02_IMPROVEMENTS_IMPLEMENTED.md
    ├── 03_BUG_FIX_DETAILS.md
    └── 04_TESTING_GUIDE.md
```

## Key Files

### Production Pipeline (Working)
- **`news_pipeline_single_run.py`** - Original pipeline with generic evaluation
  - Outputs to: `خبر فوری/`
  - Uses single evaluation prompt for all categories
  - Evaluates 'other' category (wastes API calls)
  - Status: ✅ Working correctly

### Test Pipeline (Improved, Bug Fixed)
- **`news_pipeline_test_version.py`** - New pipeline with improvements
  - Outputs to: `TEST_OUTPUT/` (moved from `خبر فوری/TEST_OUTPUT/`)
  - Uses category-specific expert personas
  - Skips evaluation for 'other' category (49% cost savings)
  - Generates TXT files automatically
  - Status: ✅ Bug fixed, ready for testing

### Supporting Files
- **`prompt_improvements.py`** - New prompt templates
  - `new_classification_prompt()` - Improved classification
  - `new_security_evaluation_prompt()` - Security analyst persona
  - `new_economics_evaluation_prompt()` - Economics analyst persona
  - `new_mixed_evaluation_prompt()` - Strategic analyst persona

## Database Statistics

### Production Database (خبر فوری/)
- Total articles: 5,503
- Security: 1,861 (33.8%)
- Economics: 219 (4.0%)
- Security/Economics: 724 (13.2%)
- Other: 2,699 (49.0%)
- Notified articles: ~2,000+
- `important_news.txt`: 11,005 lines

### Test Database (TEST_OUTPUT/)
- Total articles: 561 (sample run)
- Security: 134 (23.9%)
- Economics: 39 (7.0%)
- Security/Economics: 123 (21.9%)
- Other: 265 (47.2%)
- Notified articles: 0 → Should be ~100-150 after fix
- `important_news.txt`: 0 lines → Should be ~500-800 after fix

## Recent Changes

### File Structure Update (April 23, 2026)
- Moved `TEST_OUTPUT/` from `خبر فوری/TEST_OUTPUT/` to `NEWS_AI_PROJECT/TEST_OUTPUT/`
- Updated `news_pipeline_test_version.py` to reference new location
- Updated all documentation to reflect new paths

### Bug Fix (April 22, 2026)
- Fixed `validate_level()` function to handle empty strings
- Issue: Empty `security_relevance` field caused all notifications to fail
- Fix: Added check for empty strings before validation
- Status: Applied to `news_pipeline_test_version.py`

## Quick Start

### Run Production Pipeline
```bash
cd "/Users/parham/Downloads/PERSONAL PROJECTS/NEWS_AI_PROJECT"
python3 news_pipeline_single_run.py
```

### Run Test Pipeline
```bash
cd "/Users/parham/Downloads/PERSONAL PROJECTS/NEWS_AI_PROJECT"
python3 news_pipeline_test_version.py
```

### Check Results
```bash
# Production
wc -l "خبر فوری/important_news.txt"
ls -lh "خبر فوری/TXT Files/"

# Test
wc -l "TEST_OUTPUT/important_news.txt"
ls -lh "TEST_OUTPUT/TXT Files/"
```

## Next Steps

1. **Test the fixed pipeline** - Run `news_pipeline_test_version.py`
2. **Verify bug fix** - Check that `important_news.txt` is populated
3. **Compare outputs** - Production vs Test quality assessment
4. **Integrate improvements** - If satisfied, merge into production

See `04_TESTING_GUIDE.md` for detailed testing instructions.
