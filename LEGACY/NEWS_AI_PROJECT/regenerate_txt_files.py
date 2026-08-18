#!/usr/bin/env python3
"""
Regenerate all TXT files with new clean format (no word count warnings, proper spacing).
This script updates both production and test output files.
"""

import sys
from pathlib import Path

# Import from the main pipeline
sys.path.insert(0, str(Path(__file__).parent))

from news_pipeline_single_run import NewsPipeline as ProductionPipeline
from news_pipeline_test_version import NewsPipeline as TestPipeline

def main():
    print("=" * 80)
    print("REGENERATING TXT FILES WITH NEW FORMAT")
    print("=" * 80)
    
    # Regenerate production files
    print("\n[1/2] Regenerating PRODUCTION files (خبر فوری/)...")
    prod_pipeline = ProductionPipeline()
    database, tracking, costs = prod_pipeline.load_state()
    
    print(f"  - Rebuilding important_news.txt...")
    prod_pipeline.rebuild_notifications(database)
    
    print(f"  - Rebuilding category TXT files...")
    prod_pipeline.rebuild_txt_files(database)
    
    prod_pipeline.save_state(database, tracking, costs)
    print("  ✓ Production files regenerated")
    
    # Regenerate test files
    print("\n[2/2] Regenerating TEST files (TEST_OUTPUT/)...")
    test_pipeline = TestPipeline()
    database, tracking, costs = test_pipeline.load_state()
    
    print(f"  - Rebuilding important_news.txt...")
    test_pipeline.rebuild_notifications(database)
    
    print(f"  - Rebuilding category TXT files...")
    test_pipeline.rebuild_txt_files(database)
    
    test_pipeline.save_state(database, tracking, costs)
    print("  ✓ Test files regenerated")
    
    print("\n" + "=" * 80)
    print("REGENERATION COMPLETE")
    print("=" * 80)
    print("\nAll TXT files now have:")
    print("  - Clean format (no word count warnings)")
    print("  - Proper spacing (blank lines between sections)")
    print("  - Wrapped text for 'other' category (120 char limit)")

if __name__ == "__main__":
    main()
