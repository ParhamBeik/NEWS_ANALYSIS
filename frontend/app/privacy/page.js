import LegalPage from "@/components/LegalPage";
import { language } from "@/lib/language";

export const metadata = { title: "حریم خصوصی · Privacy · News Intelligence" };

// Keep in step with what the code stores: accounts.Account (phone, email, dial, quiet hours),
// accounts.Watch, accounts.Device, accounts.Alert, and AccountView.delete (immediate cascade).
const UPDATED = { fa: "۱۰ مهر ۱۴۰۵", en: "2 October 2026" };

const DOC = {
  fa: {
    title: "سیاست حریم خصوصی",
    sections: [
      { heading: "خلاصه", body: [
        "رادار خبر را بدون حساب کاربری هم می‌توانید بخوانید. اگر حساب بسازید، فقط همان چیزی را نگه می‌داریم که برای فهرست پیگیری و هشدارها لازم است. هیچ ابزار تحلیل یا ردیاب شخص ثالثی در وب‌سایت و اپ نیست و داده‌های شما را نمی‌فروشیم.",
      ] },
      { heading: "چه چیزی نگه می‌داریم", body: [
        "اطلاعات حساب شما فقط این‌هاست:",
        [
          "شمارهٔ موبایل، برای ورود با کد پیامکی؛",
          "ایمیل، فقط اگر خودتان برای خلاصهٔ روزانه وارد کنید (اختیاری)؛",
          "فهرست پیگیری و تنظیمات هشدار (حساسیت و ساعت سکوت)؛",
          "شناسهٔ اعلان دستگاه‌هایی که اعلان را روی آن‌ها روشن کرده‌اید.",
        ],
        "هشدارهایی که برایتان ساخته می‌شود در صندوق هشدارهای حساب شما می‌ماند تا آن‌ها را ببینید.",
      ] },
      { heading: "چه چیزی نگه نمی‌داریم", body: [[
        "نام، نشانی، کد ملی یا اطلاعات پرداخت نمی‌خواهیم؛",
        "ابزار تحلیل، پیکسل تبلیغاتی یا ردیاب شخص ثالث به‌کار نمی‌بریم؛",
        "فونت‌ها و فایل‌ها از سرور خودمان بارگذاری می‌شوند، نه از سرویس‌های خارجی؛",
        "کد ورود پیامکی فقط چند دقیقه و به‌صورت رمزنگاری‌شده نگه داشته می‌شود.",
      ]] },
      { heading: "کوکی‌ها و حافظهٔ دستگاه", body: [
        "وب‌سایت دو کوکی ضروری دارد: کوکی ورود (فقط وقتی وارد شده‌اید) و کوکی زبان. اپ اندروید کلید ورود را در حافظهٔ امن دستگاه و آخرین خبرها و هشدارها را حداکثر ۴۸ ساعت برای استفادهٔ آفلاین نگه می‌دارد؛ با خروج، دادهٔ حساب از حافظهٔ دستگاه پاک می‌شود.",
      ] },
      { heading: "با چه کسانی به اشتراک گذاشته می‌شود", body: [
        "فقط با سرویس‌هایی که برای کار خود سرویس لازم‌اند:",
        [
          "سرویس پیامک، برای فرستادن کد ورود به شمارهٔ شما؛",
          "سرویس اعلان (مانند Firebase، Pushe یا Najva)، برای رساندن اعلان به دستگاهی که خودتان روشن کرده‌اید؛",
          "سرویس ایمیل، فقط اگر خلاصهٔ ایمیلی را روشن کرده باشید.",
        ],
        "سرور برای امنیت و جلوگیری از سوءاستفاده ممکن است نشانی IP و زمان درخواست‌ها را برای مدت کوتاه در گزارش‌های فنی ثبت کند. از این گزارش‌ها برای ساختن نمایه از شما استفاده نمی‌شود.",
      ] },
      { heading: "حذف حساب", body: [
        "هر وقت بخواهید می‌توانید حساب خود را از صفحهٔ تنظیمات (وب‌سایت یا اپ) حذف کنید. با حذف حساب، شمارهٔ موبایل، ایمیل، فهرست پیگیری، شناسه‌های دستگاه و هشدارهای شما پاک می‌شود. در حال حاضر این کار بلافاصله انجام می‌شود و در هر حال حداکثر ظرف ۳۰ روز کامل می‌شود. نسخه‌های پشتیبان سرور به‌طور منظم جایگزین می‌شوند و حساب حذف‌شده با چرخش آن‌ها از پشتیبان‌ها هم حذف می‌شود.",
      ] },
      { heading: "تغییرات", body: [
        "اگر این سیاست تغییر کند، تاریخ بالای این صفحه به‌روز می‌شود. تغییری که دادهٔ بیشتری از شما بخواهد پیش از اجرا در وب‌سایت و اپ اعلام می‌شود.",
      ] },
    ],
  },
  en: {
    title: "Privacy policy",
    sections: [
      { heading: "Summary", body: [
        "You can read the news radar without an account. If you create one, we keep only what the watchlist and alerts need. There are no third-party analytics or trackers on the website or in the app, and we do not sell your data.",
      ] },
      { heading: "What we store", body: [
        "Your account holds only:",
        [
          "your mobile number, to sign you in with a texted code;",
          "an email address, only if you add one for the daily digest (optional);",
          "your watchlist and alert settings (sensitivity and quiet hours);",
          "push tokens for the devices on which you turned notifications on.",
        ],
        "Alerts created for you stay in your account's inbox so you can read them.",
      ] },
      { heading: "What we do not store", body: [[
        "We do not ask for your name, address, national ID or payment details;",
        "we use no analytics, advertising pixels or third-party trackers;",
        "fonts and files are served from our own server, not from outside services;",
        "a sign-in code is kept for a few minutes, and only in hashed form.",
      ]] },
      { heading: "Cookies and on-device storage", body: [
        "The website sets two necessary cookies: a sign-in cookie (only while you are signed in) and a language cookie. The Android app keeps its sign-in key in the device's secure store and the latest news and alerts for at most 48 hours for offline reading; signing out removes your account data from the device.",
      ] },
      { heading: "Who it is shared with", body: [
        "Only the services the product needs to work:",
        [
          "an SMS provider, to text the sign-in code to your number;",
          "a push provider (such as Firebase, Pushe or Najva), to deliver notifications to a device on which you turned them on;",
          "an email provider, only if you turned on the email digest.",
        ],
        "For security and abuse prevention, the server may briefly record IP addresses and request times in technical logs. These logs are not used to profile you.",
      ] },
      { heading: "Deleting your account", body: [
        "You can delete your account at any time from Settings, on the website or in the app. Deletion removes your mobile number, email, watchlist, device tokens and alerts. Today this happens immediately, and in every case it is complete within 30 days. Server backups are rotated on a schedule, and a deleted account drops out of them as they rotate.",
      ] },
      { heading: "Changes", body: [
        "If this policy changes, the date at the top of this page changes. A change that asks for more of your data is announced on the website and in the app before it takes effect.",
      ] },
    ],
  },
};

/** Public: listed in middleware PUBLIC, linked from the footer, the login page and the app. */
export default async function PrivacyPage() {
  const lang = await language();
  return <LegalPage doc={DOC} lang={lang} updated={UPDATED}
    other={{ href: "/terms", fa: "شرایط استفاده", en: "Terms of use" }} />;
}
