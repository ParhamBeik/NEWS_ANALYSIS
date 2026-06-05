import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re

# ==========================================
# مسیرهای دینامیک نسبت به محل اسکریپت
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(SCRIPT_DIR, "data/همه اخبار/shahrekhabar_database.json")
LATEST_FILE = os.path.join(SCRIPT_DIR, "data/همه اخبار/shahrekhabar_all_latest.json")

# اطمینان از وجود پوشه‌های مورد نیاز در مسیر دینامیک
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
os.makedirs(os.path.dirname(LATEST_FILE), exist_ok=True)

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                # اگر دیتابیس قبلی لیست بوده، آن را به دیکشنری با کلید URL تبدیل کن
                if isinstance(data, list):
                    return {item['url']: item for item in data if 'url' in item}
                return data
            except:
                return {}
    return {}

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

def update_latest(db):
    # تبدیل به لیست و مرتب‌سازی بر اساس زمان (ساعت:دقیقه) نزولی
    all_items = list(db.values())
    all_items.sort(key=lambda x: x.get('exact_published_time', '00:00'), reverse=True)
    
    with open(LATEST_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_items[:150], f, ensure_ascii=False, indent=4)

# ==========================================
# توابع پردازش زمان و اعداد
# ==========================================
def persian_to_english_numbers(text):
    if not text: return ""
    persian_nums = '۰۱۲۳۴۵۶۷۸۹'
    english_nums = '0123456789'
    return text.translate(str.maketrans(persian_nums, english_nums))

def calculate_exact_time(relative_time_str, reference_time_str=None):
    now = datetime.now()
    
    # اگر زمان مرجع از سایت شهرخبر دریافت شد (مثل ۱۶:۰۵)
    if reference_time_str:
        try:
            ref_eng = persian_to_english_numbers(reference_time_str)
            hr, mn = map(int, ref_eng.split(':'))
            now = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
        except:
            pass
            
    rel_str = persian_to_english_numbers(relative_time_str)
    match = re.search(r'\d+', rel_str)
    
    if match:
        amount = int(match.group())
        if 'دقیقه' in rel_str or 'دقيقه' in rel_str:
            exact = now - timedelta(minutes=amount)
        elif 'ساعت' in rel_str:
            exact = now - timedelta(hours=amount)
        elif 'روز' in rel_str:
            exact = now - timedelta(days=amount)
        else:
            exact = now
    else:
        exact = now
        
    return exact.strftime('%H:%M')

# ==========================================
# تابع استخراج عمیق (گذر از iframe شهرخبر و خواندن متن)
# ==========================================
def extract_deep_content(url, source):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        # ۱. ابتدا باز کردن لینک واسط شهرخبر
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # ۲. پیدا کردن لینک اصلی خبرگزاری (از داخل iframe یا meta refresh)
        original_url = None
        iframe = soup.find('iframe')
        if iframe and iframe.get('src'):
            original_url = iframe['src']
            
        if not original_url:
            meta = soup.find('meta', attrs={'http-equiv': 'refresh'})
            if meta and 'url=' in meta.get('content', '').lower():
                original_url = meta['content'].split('url=')[-1]
                
        if not original_url:
            original_url = url
            
        if not original_url.startswith('http'):
            original_url = 'https://www.shahrekhabar.com' + original_url

        # ۳. دریافت صفحه اصلی خبرگزاری
        orig_resp = requests.get(original_url, headers=headers, timeout=15)
        orig_soup = BeautifulSoup(orig_resp.text, 'html.parser')
        
        lead = ""
        text = ""
        
        # ۴. تفکیک بر اساس منبع
        if 'مهر' in source:
            lead_tag = orig_soup.select_one('.item-summary')
            body_tag = orig_soup.select_one('.item-body')
        elif 'مشرق' in source:
            lead_tag = orig_soup.select_one('.item-summary, h3.lead, .news-intro')
            body_tag = orig_soup.select_one('.item-body, .item-text, .news-text')
        elif 'صد آنلاین' in source:
            lead_tag = orig_soup.select_one('.lead, .summary')
            body_tag = orig_soup.select_one('.body-text, .item-body, .content')
        else:
            # حالت پیش‌فرض برای سایر سایت‌ها (استخراج تگ‌های پاراگراف)
            lead_tag = orig_soup.select_one('.lead, .summary, .intro')
            body_tag = None
            paragraphs = orig_soup.find_all('p')
            text = '\n'.join([p.text.strip() for p in paragraphs if len(p.text.strip()) > 30])
            
        if lead_tag: lead = lead_tag.text.strip()
        if body_tag: text = body_tag.text.strip()
        
        return {
            "original_url": original_url,
            "lead": lead,
            "text": text
        }
    except Exception as e:
        print(f"[خطا در استخراج عمیق] {url}: {e}")
        return {"original_url": "", "lead": "", "text": ""}

# ==========================================
# منطق اصلی خزش
# ==========================================
def scrape_latest_news():
    # لینک صفحه آخرین اخبار شهرخبر
    url = "https://www.shahrekhabar.com/%D8%A2%D8%AE%D8%B1%DB%8C%D9%86-%D8%A7%D8%AE%D8%A8%D8%A7%D8%B1"
    print(f"در حال دریافت اخبار از: {url}")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"خطا در دریافت صفحه: {e}")
        return

    # دریافت زمان مرجع سایت شهرخبر (برای محاسبه دقیق‌تر)
    ref_time_tag = soup.find('span', id='txt')
    ref_time = ref_time_tag.text.strip() if ref_time_tag else None

    # پیدا کردن تگ‌های لیست خبرها
    news_items = soup.select('ul.news-list-items > li')
    
    db = load_db()
    fetched_count = 0

    print(f"{len(news_items)} خبر پیدا شد. پردازش ۵۰ خبر اول...")

    for item in news_items:
        if fetched_count >= 50:
            break
            
        # پیدا کردن لینک خبر
        link_tag = item.find('a', href=True)
        if not link_tag:
            continue
            
        news_url = link_tag['href']
        if not news_url.startswith('http'):
            news_url = "https://www.shahrekhabar.com" + news_url
            
        title = link_tag.text.strip()
        
        # رد کردن خبرهای خالی
        if not title:
            continue
            
        # استخراج منبع و زمان نسبی
        source_tag = item.select_one('.refrence.minw88')
        time_tag = item.select_one('.refrence.minw80')
        
        source = source_tag.text.strip() if source_tag else "ناشناس"
        relative_time = time_tag.text.strip() if time_tag else ""
        
        exact_time = calculate_exact_time(relative_time, ref_time)
        
        # ساختار اولیه درخواست شده
        news_data = {
            "title": title,
            "url": news_url,
            "source": source,
            "relative_time_text": relative_time,
            "exact_published_time": exact_time
        }
        
        # بررسی وضعیت در دیتابیس و استخراج عمیق
        if news_url not in db:
            print(f"[{fetched_count+1}/50] در حال خزش: {title[:40]}... (منبع: {source})")
            deep_data = extract_deep_content(news_url, source)
            
            # افزودن فیلدهای عمیق به دیتای اصلی
            news_data.update(deep_data)
            
            # ذخیره در کش
            db[news_url] = news_data
            save_db(db)
        else:
            # اگر خبر در کش بود اما فیلد text نداشت (اجراهای ناقص قبلی)
            if "text" not in db[news_url]:
                print(f"[{fetched_count+1}/50] بروزرسانی محتوای عمیق کش: {title[:40]}...")
                deep_data = extract_deep_content(news_url, source)
                db[news_url].update(deep_data)
                save_db(db)
            else:
                print(f"[{fetched_count+1}/50] (تکراری - رد شد) موجود در دیتابیس.")
                
        fetched_count += 1
        
    update_latest(db)
    print(f"\nعملیات با موفقیت پایان یافت. فایل‌های شما در مسیر دینامیک زیر آپدیت شدند:\n{LATEST_FILE}")

if __name__ == "__main__":
    scrape_latest_news()
