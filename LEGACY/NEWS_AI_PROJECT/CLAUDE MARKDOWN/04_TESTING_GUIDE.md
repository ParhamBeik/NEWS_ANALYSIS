# Testing Guide - Test Pipeline vs Production

**Last Updated:** April 23, 2026  
**Status:** Ready for testing

## Overview

This guide provides step-by-step instructions for testing the improved pipeline and comparing it with production.

## Prerequisites

- Bug fix applied to `news_pipeline_test_version.py` ✅
- File structure updated (TEST_OUTPUT moved to project root) ✅
- Internet connection working
- API key valid and accessible

## Testing Workflow

### Step 1: Run Test Pipeline

```bash
cd "/Users/parham/Downloads/PERSONAL PROJECTS/NEWS_AI_PROJECT"
python3 news_pipeline_test_version.py
```

**Expected Output:**
- Fetches latest news from khabarfoori.com
- Classifies articles into categories
- Evaluates security/economics/mixed articles (skips 'other')
- Generates TXT files
- Updates database and Excel files
- Creates logs

**Duration:** ~5-10 minutes depending on number of new articles

### Step 2: Verify Bug Fix Worked

#### Check 1: important_news.txt is Populated
```bash
wc -l "TEST_OUTPUT/important_news.txt"
```
**Expected:** > 0 lines (should be ~500-800 for full database)  
**If 0:** Bug fix didn't work, check logs for errors

#### Check 2: Notified Articles Count
```bash
python3 -c "import json; db = json.load(open('TEST_OUTPUT/JSON Files/news_database.json')); print(f'Notified: {len([a for a in db.values() if a.get(\"notified\")])}')"
```
**Expected:** > 0 (should be ~100-150 for sample run)  
**If 0:** Bug still present, check security_relevance values

#### Check 3: Security Relevance Values
```bash
python3 -c "import json; db = json.load(open('TEST_OUTPUT/JSON Files/news_database.json')); sec = [a for a in db.values() if a.get('classification_category') == 'security']; print(f'Empty: {len([a for a in sec if a.get(\"security_relevance\") == \"\"])}'); print(f'Valid: {len([a for a in sec if a.get(\"security_relevance\") and a.get(\"security_relevance\") != \"\"])}')"
```
**Expected:** Empty: 0, Valid: ~134  
**If Empty > 0:** validate_level fix didn't work

#### Check 4: TXT Files Generated
```bash
ls -lh "TEST_OUTPUT/TXT Files/"
```
**Expected:** 4 files (security_news.txt, economics_news.txt, security_economics_news.txt, other_news.txt)  
**All should have size > 0**

### Step 3: Compare Outputs

#### Compare important_news.txt
```bash
# Check line counts
wc -l "خبر فوری/important_news.txt" "TEST_OUTPUT/important_news.txt"

# View first 50 lines of each
head -50 "خبر فوری/important_news.txt"
head -50 "TEST_OUTPUT/important_news.txt"
```

**What to Look For:**
- Are the same important articles appearing in both?
- Is the test version missing any critical news?
- Is the test version including irrelevant news?

#### Compare TXT Files
```bash
# Check if production has TXT files
ls -lh "خبر فوری/TXT Files/" 2>/dev/null || echo "Production doesn't have TXT files yet"

# View test TXT files
head -30 "TEST_OUTPUT/TXT Files/security_news.txt"
head -30 "TEST_OUTPUT/TXT Files/economics_news.txt"
```

**What to Look For:**
- Are articles properly categorized?
- Is the format readable and useful?
- Are summaries accurate and concise?

#### Compare API Costs
```bash
python3 << 'PYEOF'
import json

prod = json.load(open('خبر فوری/JSON Files/api_costs.json'))
test = json.load(open('TEST_OUTPUT/JSON Files/api_costs.json'))

print("Production API Costs:")
print(f"  Total: ${prod.get('total_cost_usd', 0):.2f}")
print(f"  Classification: {prod.get('classification', {}).get('call_count', 0)} calls")
print(f"  Evaluation: {prod.get('evaluation', {}).get('call_count', 0)} calls")
print(f"  Compression: {prod.get('compression', {}).get('call_count', 0)} calls")

print("\nTest API Costs:")
print(f"  Total: ${test.get('total_cost_usd', 0):.2f}")
print(f"  Classification: {test.get('classification', {}).get('call_count', 0)} calls")
print(f"  Evaluation: {test.get('evaluation', {}).get('call_count', 0)} calls")
print(f"  Compression: {test.get('compression', {}).get('call_count', 0)} calls")

if prod.get('evaluation', {}).get('call_count', 0) > 0:
    savings = 1 - (test.get('evaluation', {}).get('call_count', 0) / prod.get('evaluation', {}).get('call_count', 1))
    print(f"\nEvaluation Call Savings: {savings*100:.1f}%")
PYEOF
```

**Expected:** Test version should have ~49% fewer evaluation calls

### Step 4: Quality Assessment

#### Classification Accuracy

**Manual Review:**
1. Open `TEST_OUTPUT/TXT Files/security_news.txt`
2. Scan first 20 articles
3. Ask yourself: "Are these actually security-related?"
4. Repeat for economics and mixed categories

**Common Issues to Check:**
- False positives: Non-security news in security_news.txt
- False negatives: Important security news in other_news.txt
- Mixed category overuse: Articles that should be single-category

#### Evaluation Quality

**Check Security Articles:**
```bash
python3 << 'PYEOF'
import json

db = json.load(open('TEST_OUTPUT/JSON Files/news_database.json'))
sec = [a for a in db.values() if a.get('classification_category') == 'security' and a.get('processed')][:5]

print("Sample Security Article Evaluations:\n")
for i, a in enumerate(sec, 1):
    print(f"{i}. {a.get('original_title', '')[:60]}")
    print(f"   Confidence: {a.get('confidence_occurrence')}")
    print(f"   Security Relevance: {a.get('security_relevance')}")
    print(f"   Gold Impact: {a.get('gold_price_impact')}")
    print(f"   Rationale: {a.get('evaluation_rationale', '')[:80]}")
    print(f"   Notified: {a.get('notified')}\n")
PYEOF
```

**What to Look For:**
- Are security_relevance scores reasonable?
- Are gold_price_impact values correctly set to "خیلی کم" (default)?
- Do rationales make sense?

**Check Economics Articles:**
```bash
python3 << 'PYEOF'
import json

db = json.load(open('TEST_OUTPUT/JSON Files/news_database.json'))
econ = [a for a in db.values() if a.get('classification_category') == 'economics' and a.get('processed')][:5]

print("Sample Economics Article Evaluations:\n")
for i, a in enumerate(econ, 1):
    print(f"{i}. {a.get('original_title', '')[:60]}")
    print(f"   Confidence: {a.get('confidence_occurrence')}")
    print(f"   Gold Impact: {a.get('gold_price_impact')}")
    print(f"   Security Relevance: {a.get('security_relevance')}")
    print(f"   Rationale: {a.get('evaluation_rationale', '')[:80]}")
    print(f"   Notified: {a.get('notified')}\n")
PYEOF
```

**What to Look For:**
- Are gold_price_impact scores reasonable?
- Are security_relevance values correctly set to "خیلی کم" (default)?
- Do rationales focus on economic factors?

### Step 5: Decision Point

Based on your assessment, decide:

#### Option A: Test Version is Better ✅
**Actions:**
1. Backup production pipeline
2. Integrate improvements into production
3. Clean up obsolete files
4. Update documentation

See "Integration Steps" below.

#### Option B: Test Version Needs Improvement ⚠️
**Actions:**
1. Document specific issues found
2. Adjust prompts in `prompt_improvements.py`
3. Re-run test pipeline
4. Repeat comparison

See "Troubleshooting" below.

#### Option C: Keep Both Versions 🔄
**Actions:**
1. Continue running both pipelines
2. Compare over longer period
3. Gather more data before decision

## Integration Steps (If Test is Better)

### Step 1: Backup Production
```bash
cd "/Users/parham/Downloads/PERSONAL PROJECTS/NEWS_AI_PROJECT"
cp news_pipeline_single_run.py news_pipeline_single_run.py.OLD
```

### Step 2: Update Production Pipeline
```bash
# Copy test version to production
cp news_pipeline_test_version.py news_pipeline_single_run.py

# Update paths in production file (change TEST_OUTPUT back to خبر فوری)
sed -i.bak 's|BASE_DIR / "TEST_OUTPUT"|BASE_DIR / "خبر فوری"|' news_pipeline_single_run.py
```

### Step 3: Verify Production Paths
```bash
grep "RUNTIME_DIR" news_pipeline_single_run.py
# Should show: RUNTIME_DIR = BASE_DIR / "خبر فوری"
```

### Step 4: Test Production Pipeline
```bash
python3 news_pipeline_single_run.py
```

### Step 5: Clean Up Obsolete Files
```bash
# Delete old test files
rm test_new_prompts.py
rm test_pipeline_comprehensive.py
rm generate_txt_files.py

# Delete old markdown files (now in CLAUDE MARKDOWN/)
rm IMPLEMENTATION_SUMMARY.md
rm TEST_VERSION_README.md
rm BUG_FIX_SUMMARY.md
rm FINAL_SUMMARY.md
rm BUG_ANALYSIS_AND_FIX.md
rm FINAL_STATUS_AND_NEXT_STEPS.md
rm PROJECT_IMPROVEMENTS_COMPLETE.md

# Keep only:
# - PROJECT_DOCUMENTATION.md (or move to CLAUDE MARKDOWN/)
# - CLAUDE MARKDOWN/ folder

# Optionally delete TEST_OUTPUT
rm -rf TEST_OUTPUT
```

## Troubleshooting

### Issue: important_news.txt Still Empty

**Check 1: Evaluation Status**
```bash
python3 -c "import json; db = json.load(open('TEST_OUTPUT/JSON Files/news_database.json')); statuses = [a.get('evaluation_status') for a in db.values() if a.get('processed')]; from collections import Counter; print(Counter(statuses))"
```

**Check 2: Notification Status**
```bash
python3 -c "import json; db = json.load(open('TEST_OUTPUT/JSON Files/news_database.json')); statuses = [a.get('notification_status') for a in db.values() if a.get('processed')]; from collections import Counter; print(Counter(statuses))"
```

**Check 3: Logs**
```bash
tail -100 TEST_OUTPUT/LOG Files/*.log
```

### Issue: API Errors

**Check Internet Connection:**
```bash
ping -c 3 api.gapgpt.app
```

**Check API Key:**
```bash
python3 -c "import os; print('API Key:', os.getenv('GAPGPT_API_KEY', 'NOT SET')[:20] + '...')"
```

**Check Logs for Errors:**
```bash
grep -i "error" TEST_OUTPUT/LOG Files/*.log
```

### Issue: Classification Seems Wrong

**Review Classification Memory:**
```bash
cat "TEST_OUTPUT/Markdown Files/classification_memory.md"
```

**Check Classification Confidence:**
```bash
python3 -c "import json; db = json.load(open('TEST_OUTPUT/JSON Files/news_database.json')); confs = [a.get('classification_confidence') for a in db.values() if a.get('processed')]; from collections import Counter; print(Counter(confs))"
```

**If many "کم" or "خیلی کم":** Classification is uncertain, may need prompt adjustment

### Issue: Evaluation Seems Wrong

**Check Evaluation Rationales:**
```bash
python3 << 'PYEOF'
import json

db = json.load(open('TEST_OUTPUT/JSON Files/news_database.json'))
articles = [a for a in db.values() if a.get('processed') and a.get('notified')][:10]

for a in articles:
    print(f"Title: {a.get('original_title', '')[:60]}")
    print(f"Category: {a.get('classification_category')}")
    print(f"Rationale: {a.get('evaluation_rationale', '')}")
    print("-" * 80)
PYEOF
```

**If rationales don't make sense:** Adjust prompts in `prompt_improvements.py`

## Success Criteria

The test version is successful if:

- ✅ `important_news.txt` is populated (> 0 lines)
- ✅ Notified articles > 0
- ✅ No empty `security_relevance` or `gold_price_impact` values
- ✅ Classification accuracy is good (manual review)
- ✅ Evaluation quality is good (rationales make sense)
- ✅ TXT files are useful and well-organized
- ✅ API costs are lower (~49% fewer evaluation calls)
- ✅ No critical news is missed
- ✅ No irrelevant news is over-emphasized

## Next Steps

After successful testing and integration:
1. Monitor production pipeline for a few days
2. Compare results with old system
3. Adjust prompts if needed
4. Document any issues or improvements
5. Consider further optimizations

## Support

If you encounter issues not covered in this guide:
1. Check LOG files in `TEST_OUTPUT/LOG Files/`
2. Review database JSON for anomalies
3. Compare with production database
4. Check API response logs
5. Review prompt templates in `prompt_improvements.py`
