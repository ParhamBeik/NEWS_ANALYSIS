# News Pipeline Documentation

**Last Updated:** April 23, 2026  
**Created by:** Claude (Anthropic AI Assistant)

## About This Documentation

This folder contains comprehensive documentation for the Iranian News Pipeline project, created during a debugging and improvement session.

## Document Structure

### 📋 [01_PROJECT_OVERVIEW.md](01_PROJECT_OVERVIEW.md)
- Complete project summary
- File structure and organization
- Database statistics
- Quick start guide
- Recent changes log

### 🔧 [02_IMPROVEMENTS_IMPLEMENTED.md](02_IMPROVEMENTS_IMPLEMENTED.md)
- Detailed description of all improvements
- Phase 1: TXT file organization
- Phase 2: Prompt system redesign
- Phase 3: Test version creation
- Expected benefits and cost savings

### 🐛 [03_BUG_FIX_DETAILS.md](03_BUG_FIX_DETAILS.md)
- Complete bug analysis
- Root cause investigation
- Fix implementation
- Testing procedures
- Prevention strategies

### 🧪 [04_TESTING_GUIDE.md](04_TESTING_GUIDE.md)
- Step-by-step testing instructions
- Verification procedures
- Quality assessment guidelines
- Integration steps
- Troubleshooting guide

## Quick Navigation

### I want to...

**Understand the project**
→ Start with `01_PROJECT_OVERVIEW.md`

**Learn about improvements**
→ Read `02_IMPROVEMENTS_IMPLEMENTED.md`

**Understand the bug fix**
→ Check `03_BUG_FIX_DETAILS.md`

**Test the system**
→ Follow `04_TESTING_GUIDE.md`

## Key Changes Summary

### File Structure Update (April 23, 2026)
- Moved `TEST_OUTPUT/` from `خبر فوری/TEST_OUTPUT/` to project root
- Updated all code references
- Updated all documentation

### Bug Fix (April 22, 2026)
- Fixed `validate_level()` function to handle empty strings
- Resolved notification system failure
- Applied to `news_pipeline_test_version.py`

### Improvements Implemented
1. **TXT File Organization** - Category-specific output files
2. **Category-Specific Evaluation** - Expert personas for each category
3. **Time-Windowed Memory** - 30-day window to reduce bias
4. **Cost Optimization** - Skip 'other' category evaluation (49% savings)

## Current Status

### Production Pipeline ✅
- **File:** `news_pipeline_single_run.py`
- **Status:** Working correctly
- **Output:** `خبر فوری/`
- **Prompts:** Original generic evaluation

### Test Pipeline ✅
- **File:** `news_pipeline_test_version.py`
- **Status:** Bug fixed, ready for testing
- **Output:** `TEST_OUTPUT/`
- **Prompts:** New category-specific evaluation

## Next Steps

1. Run test pipeline: `python3 news_pipeline_test_version.py`
2. Verify bug fix worked (see `04_TESTING_GUIDE.md`)
3. Compare outputs with production
4. Decide on integration

## Files in This Folder

```
CLAUDE MARKDOWN/
├── 00_README.md                      # This file
├── 01_PROJECT_OVERVIEW.md            # Project summary
├── 02_IMPROVEMENTS_IMPLEMENTED.md    # Detailed improvements
├── 03_BUG_FIX_DETAILS.md            # Bug analysis and fix
└── 04_TESTING_GUIDE.md              # Testing instructions
```

## Original Markdown Files

The following files were consolidated into this documentation:
- `IMPLEMENTATION_SUMMARY.md`
- `TEST_VERSION_README.md`
- `BUG_FIX_SUMMARY.md`
- `FINAL_SUMMARY.md`
- `BUG_ANALYSIS_AND_FIX.md`
- `FINAL_STATUS_AND_NEXT_STEPS.md`
- `PROJECT_IMPROVEMENTS_COMPLETE.md`
- `PROJECT_DOCUMENTATION.md`


## Contact & Support

This documentation was created by Claude AI assistant during a debugging session. For questions or issues:

1. Review the relevant documentation file
2. Check the troubleshooting section in `04_TESTING_GUIDE.md`
3. Review LOG files in `TEST_OUTPUT/LOG Files/`
4. Compare with production pipeline behavior

## Version History

- **v1.0** (April 23, 2026) - Initial consolidated documentation
  - Created from 8 separate markdown files
  - Updated all paths for new TEST_OUTPUT location
  - Added comprehensive testing guide
  - Organized into logical sections

## License & Usage

This documentation is part of the News Pipeline project and is intended for internal use. Feel free to modify and update as the project evolves.
