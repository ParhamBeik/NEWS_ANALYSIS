import os
import sys
import json
import time
import requests
from bs4 import BeautifulSoup

# --- تنظیمات پایه ---
BASE_LIST_URL = "https://www.khabarfoori.com/بخش-اخبار-2" 
DOMAIN = "https://www.khabarfoori.com"
MAX_PAGES = 15

# --- تنظیمات مسیرهای پویا (اصلاح شده) ---
# پیدا کردن مسیر دقیق دایرکتوری که همین فایل اسکریپت در آن قرار دارد
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
AGENCY_DIR = os.path.join(DATA_DIR, "خبر فوری")
DATABASE_FILE = os.path.join(AGENCY_DIR, "all_news_database.json")

def setup_directories():
    """ایجاد پوشه‌های مورد نیاز در صورت عدم وجود در کنار فایل اسکریپت"""
    os.makedirs(AGENCY_DIR, exist_ok=True)
    print(f"پوشه خروجی ایجاد/تایید شد: {AGENCY_DIR}")

def load_database():
    """بارگذاری دیتابیس مرکزی اخبار"""
    if os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_database(db_data):
    """به‌روزرسانی و ذخیره دیتابیس مرکزی"""
    with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, ensure_ascii=False, indent=4)

def extract_news_links(html_content):
    """استخراج لینک اخبار از صفحات لیست"""
    soup = BeautifulSoup(html_content, 'html.parser')
    page_links = []
    
    news_list_container = soup.find('ul', class_='box container')
    
    if not news_list_container:
        print("خطا: محفظه‌ی اصلی لیست اخبار پیدا نشد.")
        sys.exit(1)

    for h2_tag in news_list_container.find_all('h2', class_='title'):
        link_tag = h2_tag.find('a', href=True)
        if link_tag:
            href = link_tag['href']
            full_url = f"{DOMAIN}{href}" if not href.startswith('http') else href
                
            if full_url not in page_links:
                page_links.append(full_url)
    
    if len(page_links) > 10:
        print("\n--- هشدار توقف خودکار ---")
        print(f"تعداد لینک‌ها ({len(page_links)}) بیش از حد انتظار (10) است.")
        sys.exit(1)
        
    return page_links

def extract_article_data(article_url):
    """استخراج دقیق اطلاعات با استفاده از تحلیل ترکیبی اسکیما و کدهای نمایشی"""
    try:
        response = requests.get(article_url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # متغیرهای پیش‌فرض
        title = "بدون تیتر"
        lead = "بدون لید"
        text = "متن خبر پیدا نشد"
        date_text = "بدون تاریخ"
        datetime_attr = ""

        # استراتژی اول: استخراج از دیتای ساختاریافته (بسیار دقیق و ضدخطا)
        schemas = soup.find_all('script', type='application/ld+json')
        for script in schemas:
            try:
                if script.string:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get('@type') == 'NewsArticle':
                        title = data.get('headline', title)
                        lead = data.get('description', lead)
                        datetime_attr = data.get('datePublished', datetime_attr)
                        break
            except json.JSONDecodeError:
                continue

        # استراتژی دوم: جایگزین و تکمیل داده‌ها از طریق کدهای نمایشی
        if title == "بدون تیتر":
            title_tag = soup.find('h1', class_='title')
            if title_tag:
                title = title_tag.text.strip()

        if lead == "بدون لید":
            lead_tag = soup.find('p', class_='lead')
            if lead_tag:
                lead = lead_tag.text.strip()

        text_parts = []
        editor_container = soup.find('div', id='main_ck_editor')
        if editor_container:
            for p_tag in editor_container.find_all('p'):
                p_text = p_tag.text.strip()
                if p_text:
                    text_parts.append(p_text)
            if text_parts:
                text = "\n".join(text_parts)

        time_container = soup.find('span', class_='news_time')
        if time_container:
            time_tag = time_container.find('time')
            if time_tag:
                date_text = time_tag.text.strip()
                if not datetime_attr:
                    datetime_attr = time_tag.get('datetime', '')
            
        return {
            "url": article_url,
            "title": title,
            "lead": lead,
            "text": text,
            "published_date_text": date_text,
            "published_datetime": datetime_attr
        }
    except Exception as e:
        print(f"  [!] خطا در استخراج خبر {article_url}: {e}")
        return None

def start_crawling():
    """مدیریت فرآیند خزش و تفکیک داده‌ها"""
    setup_directories()
    
    master_db = load_database()
    print(f"دیتابیس مرکزی با {len(master_db)} خبر بارگذاری شد.")
    
    new_articles_count = 0
    total_links_processed = 0

    for page in range(1, MAX_PAGES + 1):
        print(f"\n[{page}/{MAX_PAGES}] پردازش صفحه {page} ...")
        page_url = f"{BASE_LIST_URL}/?page={page}"
        
        try:
            response = requests.get(page_url, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"خطا در دریافت صفحه {page}: {e}")
            continue
            
        links = extract_news_links(response.text)
        print(f"  - یافتن {len(links)} لینک معتبر.")
        total_links_processed += len(links)
        
        page_data = []
        
        for link in links:
            if link in master_db:
                print(f"    * بارگذاری سریع (موجود در سیستم): {link.split('/')[-1]}")
                page_data.append(master_db[link])
            else:
                print(f"    + دریافت و آنالیز خبر جدید: {link.split('/')[-1]}")
                article_data = extract_article_data(link)
                
                if article_data:
                    page_data.append(article_data)
                    master_db[link] = article_data 
                    new_articles_count += 1
                
                time.sleep(1) # وقفه امنیتی
            
        output_file = os.path.join(AGENCY_DIR, f"khabarfoori_page{page}.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(page_data, f, ensure_ascii=False, indent=4)
            
        print(f"  - فایل صفحه {page} با موفقیت در پوشه 'خبر فوری' نوشته شد.")
        time.sleep(1)

    save_database(master_db)
    
    print("\n" + "#"*40)
    print("گزارش پایان عملیات:")
    print(f"- کل لینک‌های بررسی شده: {total_links_processed}")
    print(f"- اخبار جدید کشف و استخراج شده: {new_articles_count}")
    print(f"- مجموع داده‌های ذخیره شده در هسته مرکزی: {len(master_db)}")
    print(f"- مسیر ذخیره‌سازی داده‌ها: {AGENCY_DIR}")
    print("#"*40)

if __name__ == "__main__":
    print("آماده‌سازی موتور خزشگر...")
    start_crawling()
