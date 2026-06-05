# Pipeline Improvements - Implementation Details

**Last Updated:** April 23, 2026

## Overview

This document describes all improvements made to the news pipeline system, including the rationale, implementation, and expected benefits.

## Phase 1: TXT File Organization ✅

### Problem
- All news mixed together in single `important_news.txt` file
- Hard to scan by category
- No easy way to review security vs economics news separately

### Solution
Created category-specific TXT files in `TXT Files/` directory:
- `security_news.txt` - Security-related articles only
- `economics_news.txt` - Economics-related articles only
- `security_economics_news.txt` - Mixed category articles
- `other_news.txt` - Non-relevant articles

### Format
```
[Title]

[Summary/Lead]

[Source] | [Persian Date] | [Time]
--------------------------------------------------
```

### Implementation Details
- Security/Economics/Mixed: Uses AI-generated `one_line_description`
- Other: Uses `lead` (no API cost for summary generation)
- Sorted newest first for easy scanning
- Automatically generated during pipeline execution

### Results (Production Database)
- `security_news.txt`: 1,861 articles (872KB)
- `economics_news.txt`: 219 articles (102KB)
- `security_economics_news.txt`: 724 articles (347KB)
- `other_news.txt`: 2,699 articles (1.2MB)

## Phase 2: Prompt System Redesign ✅

### Problems Identified

1. **Generic Evaluation**
   - Single evaluation prompt for all categories
   - Security news evaluated with same lens as economics news
   - No specialized expertise applied

2. **Outdated Memory Bias**
   - Memory includes all historical data
   - Old patterns dominate classification decisions
   - Novel/sudden important news might be undervalued

3. **Keyword-Focused Classification**
   - Too focused on scattered keywords
   - Misses main meaning and context
   - False positives/negatives

4. **Wasted API Calls**
   - Evaluating 'other' category (49% of articles)
   - These articles never get notified anyway
   - Significant cost with no benefit

### Solutions Implemented

#### 2.1 Category-Specific Expert Personas

Created specialized evaluation prompts in `prompt_improvements.py`:

**Security Evaluation** (`new_security_evaluation_prompt`)
- **Persona:** Security analyst for Iran
- **Focus:** Direct/indirect security risks, military threats, geopolitics
- **Evaluates:** 
  - `confidence_occurrence` - How reliable is this news?
  - `security_relevance` - How much does it affect Iran's security?
  - `gold_trend` - Impact on gold prices
- **Skips:** `gold_price_impact` (not relevant for pure security news)

**Economics Evaluation** (`new_economics_evaluation_prompt`)
- **Persona:** Economics analyst for Iran
- **Focus:** Economic impact, gold prices, inflation, currency
- **Evaluates:**
  - `confidence_occurrence` - How reliable is this news?
  - `gold_price_impact` - Direct impact on gold prices
  - `gold_trend` - Direction of gold price movement
- **Skips:** `security_relevance` (not relevant for pure economics news)
- **Special Logic:** Iran-specific factors (dollar, rial, sanctions, inflation)

**Mixed Evaluation** (`new_mixed_evaluation_prompt`)
- **Persona:** Strategic analyst for Iran
- **Focus:** BOTH security AND economic dimensions equally
- **Evaluates:** All fields
  - `confidence_occurrence`
  - `security_relevance`
  - `gold_price_impact`
  - `gold_trend`
- **Purpose:** Ensure dual-impact news is evaluated comprehensively

**Other Category**
- **Action:** Skip evaluation entirely
- **Rationale:** These articles won't be notified anyway
- **Benefit:** Saves ~2,699 API calls per full database process (49% savings)

#### 2.2 Time-Windowed Memory (30 Days)

**Implementation:**
- Added `filter_memory_by_time_window()` function
- Memory now only includes last 30 days of articles
- Filters out outdated patterns

**Benefits:**
- Prevents old patterns from dominating decisions
- Allows system to adapt to new geopolitical situations
- Reduces bias against novel/sudden important news
- Still provides enough context for calibration

**Example:**
- Old pattern: "Negotiations with US always classified as security"
- New situation: Negotiations break down, new conflict emerges
- With 30-day window: System adapts to new reality
- Without window: Old pattern might bias classification

#### 2.3 Category-Specific Memory

**Implementation:**
- Added `category_specific_evaluation_memory()` function
- Security evaluation sees security examples
- Economics evaluation sees economics examples

**Benefits:**
- Better calibration for each expert persona
- More relevant context for evaluation
- Reduces cross-category confusion

#### 2.4 Improved Classification Prompt

**Changes:**
- Emphasis on "main meaning" over scattered keywords
- Memory positioned as calibration tool, not decision maker
- Explicit instruction: "If news is novel/different, classify independently"
- Clearer decision tree in rubric

**Example Instruction:**
```
"اگر خبر جدید یا متفاوت از الگوهای قبلی است، مستقل و منصفانه طبقه بندی کن."
(If news is new or different from previous patterns, classify independently and fairly.)
```

## Phase 3: Test Version Creation ✅

### Implementation
- Created `news_pipeline_test_version.py` as complete copy of production
- Integrated new prompts from `prompt_improvements.py`
- Changed output directory to `TEST_OUTPUT/` (now at project root)
- Added automatic TXT file generation
- Added 'other' category skip logic

### Key Differences from Production

| Feature | Production | Test |
|---------|-----------|------|
| Output Location | `خبر فوری/` | `TEST_OUTPUT/` |
| Evaluation Prompts | Generic | Category-specific |
| Memory Window | All history | 30 days |
| 'Other' Category | Evaluated | Skipped |
| TXT Files | Manual generation | Automatic |
| API Cost | Higher | ~49% lower |

## Expected Benefits

### 1. Better Classification Accuracy
- Main meaning prioritized over keywords
- Novel news treated fairly
- Less bias from outdated patterns

### 2. Better Evaluation Quality
- Security news evaluated by security expert
- Economics news evaluated by economics expert
- Mixed news gets comprehensive dual evaluation

### 3. Significant Cost Savings
- Skip evaluation for 'other' category: ~2,699 calls saved (49%)
- Skip compression for 'other' category: ~2,699 calls saved (49%)
- Total: ~5,398 API calls saved per full database process

### 4. Better Organization
- Category-specific TXT files for easy scanning
- Newest articles first
- Human-readable format

### 5. Adaptability
- 30-day memory window allows system to adapt
- Novel geopolitical situations handled better
- Sudden important news not undervalued

## Implementation Status

### Completed ✅
1. TXT file generation logic
2. Time-windowed memory filtering
3. Balanced category sampling
4. Category-specific memory functions
5. Updated memory prompt functions
6. Refined classification rubric
7. New prompt templates created
8. Test pipeline created
9. Bug fix applied (validate_level)
10. File structure updated (TEST_OUTPUT moved)

### Testing Required ⏳
1. Run test pipeline on fresh news
2. Verify bug fix worked
3. Compare classification accuracy
4. Compare evaluation quality
5. Verify API cost savings
6. Assess TXT file usefulness

### Integration Pending ⏳
1. Compare test vs production outputs
2. User decision on quality improvement
3. Merge improvements into production (if approved)
4. Update production pipeline paths
5. Clean up obsolete files

## Technical Details

### Memory Filtering Logic
```python
def filter_memory_by_time_window(database, days=30):
    cutoff = datetime.now(TEHRAN_TZ) - timedelta(days=days)
    return [a for a in database.values() 
            if a.get('published_at_persian') >= cutoff_date]
```

### Category-Specific Evaluation Routing
```python
def evaluation_prompt(self, article, memory_text):
    category = article.get('classification_category', 'other')
    
    if category == "security":
        return new_security_evaluation_prompt(article, memory_text)
    elif category == "economics":
        return new_economics_evaluation_prompt(article, memory_text)
    elif category == "security/economics":
        return new_mixed_evaluation_prompt(article, memory_text)
    else:
        return None  # Skip evaluation for 'other'
```

### Cost Savings Calculation
```
Total articles: 5,503
Other category: 2,699 (49%)

Evaluation calls saved: 2,699
Compression calls saved: 2,699
Total API calls saved: 5,398 (49% reduction)

Estimated cost savings per full run: ~$2-3 USD
```

## Next Steps

See `04_TESTING_GUIDE.md` for detailed testing instructions.
