import requests
from bs4 import BeautifulSoup
import json
import os
import time
from urllib.parse import urljoin

# --- تنظیمات اولیه ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

CATEGORIES = {
    "Economics": 25,
    "Politics": 7,
    "Society": 6
}

# مسیرهای اصلی پروژه (پویا بر اساس محل فایل اسکریپت)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
AGENCY_DIR = os.path.join(DATA_DIR, "خبر گزاری مهر")

def load_database(filepath):
    """بارگذاری دیتابیس کش برای جلوگیری از دانلود مجدد اخبار تکراری"""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_database(filepath, db_data):
    """ذخیره و به‌روزرسانی دیتابیس کش"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=4)

def extract_article_data(url):
    """
    دریافت URL خبر و استخراج مقادیر بر اساس کلاس‌های HTML مشخص شده.
    """
    article_data = {
        "url": url,
        "title": "",
        "lead": "",
        "text": "",
        "published_date_text": ""
    }
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # ۱. استخراج تاریخ
        date_tag = soup.select_one('.item-header .item-nav .item-date span')
        if date_tag:
            article_data['published_date_text'] = date_tag.get_text(strip=True)
            
        # ۲. استخراج تیتر
        title_tag = soup.select_one('.item-title h1, .item-title .title')
        if title_tag:
            article_data['title'] = title_tag.get_text(strip=True)
            
        # ۳. استخراج لید (خلاصه)
        lead_tag = soup.select_one('.item-summary p.summary')
        if lead_tag:
            article_data['lead'] = lead_tag.get_text(strip=True)
            
        # ۴. استخراج متن اصلی
        body_div = soup.select_one('.item-body .item-text')
        if body_div:
            paragraphs = [p.get_text(strip=True) for p in body_div.find_all('p')]
            article_data['text'] = "\n\n".join(filter(None, paragraphs))
            
    except Exception as e:
        print(f"      [خطا] در دریافت یا پردازش محتوای لینک {url}: {e}")
        
    return article_data

def scrape_mehr_news(start_page=1, end_page=5):
    base_url = "https://www.mehrnews.com"
    
    # ساخت پوشه‌های اصلی
    os.makedirs(AGENCY_DIR, exist_ok=True)
    print(f"پوشه اصلی خروجی آماده است: {AGENCY_DIR}")
    
    for category_name, tp_code in CATEGORIES.items():
        category_dir = os.path.join(AGENCY_DIR, category_name)
        os.makedirs(category_dir, exist_ok=True)
        
        # مسیر فایل دیتابیس اختصاصی این دسته‌بندی
        db_filepath = os.path.join(category_dir, f"{category_name}_database.json")
        master_db = load_database(db_filepath)
        
        print(f"\n{'='*50}")
        print(f"شروع استخراج بخش: {category_name.upper()} | اخبار موجود در کش: {len(master_db)}")
        
        # لیستی برای تجمیع کل اخبار اخیر جهت استفاده LLM
        all_latest_news_for_llm = [] 
        new_articles_count = 0
        
        for page_num in range(start_page, end_page + 1):
            print(f"\n  [صفحه {page_num}] در حال استخراج لینک‌ها...")
            target_url = f"https://www.mehrnews.com/archive?tp={tp_code}&pi={page_num}"
            
            try:
                response = requests.get(target_url, headers=HEADERS, timeout=10)
                response.raise_for_status()
            except Exception as e:
                print(f"  [خطا] دریافت صفحه {page_num} شکست خورد: {e}")
                continue

            soup = BeautifulSoup(response.text, 'html.parser')
            news_items = soup.select("section.box.list ul li.news h3 a")
            
            extracted_links = []
            seen_links = set() 
            page_data = []
            
            for item in news_items:
                href = item.get('href')
                if href:
                    full_url = urljoin(base_url, href)
                    if full_url not in seen_links:
                        seen_links.add(full_url)
                        extracted_links.append(full_url)
            
            print(f"  [صفحه {page_num}] تعداد {len(extracted_links)} لینک یافت شد.")
            
            # پردازش لینک‌ها با مکانیزم دیتابیس (جلوگیری از دانلود مجدد)
            for index, url in enumerate(extracted_links, 1):
                if url in master_db:
                    print(f"    * [سریع] بارگذاری از دیتابیس محلی: {url.split('/')[-1][:30]}...")
                    article_info = master_db[url]
                else:
                    print(f"    + [جدید] دانلود و استخراج خبر: {url.split('/')[-1][:30]}...")
                    article_info = extract_article_data(url)
                    master_db[url] = article_info
                    new_articles_count += 1
                    time.sleep(1) # وقفه فقط برای اخبار جدید اعمال می‌شود
                
                page_data.append(article_info)
                all_latest_news_for_llm.append(article_info)
                
            # ذخیره فایل اختصاصی هر صفحه
            filename = f"MehrNews_{category_name}_page{page_num}.json"
            filepath = os.path.join(category_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(page_data, f, ensure_ascii=False, indent=4)
                
        # پس از پایان صفحات این دسته‌بندی، دیتابیس را به‌روزرسانی می‌کنیم
        save_database(db_filepath, master_db)
        
        # ذخیره یک فایل تجمیعی و سازماندهی شده از تمام ~150 خبر اخیر برای LLM
        combined_filepath = os.path.join(category_dir, f"{category_name}_all_latest.json")
        with open(combined_filepath, 'w', encoding='utf-8') as f:
            json.dump(all_latest_news_for_llm, f, ensure_ascii=False, indent=4)
            
        print(f"\n  => پایان بخش {category_name}.")
        print(f"  => تعداد اخبار جدید اضافه شده به دیتابیس: {new_articles_count}")
        print(f"  => فایل تجمیعی آماده برای LLM با {len(all_latest_news_for_llm)} خبر ایجاد شد: {category_name}_all_latest.json")

if __name__ == "__main__":
    print("آماده‌سازی موتور خزشگر خبرگزاری مهر...")
    start_time = time.time()
    
    scrape_mehr_news(start_page=1, end_page=5)
    
    elapsed_time = time.time() - start_time
    print("\n" + "*"*50)
    print(f"فرآیند استخراج با موفقیت در {elapsed_time:.2f} ثانیه به پایان رسید.")
