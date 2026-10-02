import LegalPage from "@/components/LegalPage";
import { language } from "@/lib/language";

export const metadata = { title: "شرایط استفاده · Terms · News Intelligence" };

const UPDATED = { fa: "۱۰ مهر ۱۴۰۵", en: "2 October 2026" };

// "Facts only with a link out" is sources.Source.LicenseMode.FACTS_LINK_OUT.
const DOC = {
  fa: {
    title: "شرایط استفاده",
    sections: [
      { heading: "این سرویس چیست", body: [
        "رادار خبر خبرهای منتشرشده دربارهٔ اقتصاد و سیاست را از منابع ایرانی و بین‌المللی گردآوری می‌کند، گزارش‌های یک رویداد را کنار هم می‌گذارد و برآورد می‌کند هر رویداد چقدر ممکن است برای سرمایه‌گذاران ایرانی اهمیت داشته باشد. برآوردها و خلاصه‌ها با کمک مدل‌های هوش مصنوعی ساخته می‌شوند و ممکن است نادرست یا ناقص باشند.",
      ] },
      { heading: "توصیهٔ سرمایه‌گذاری نیست", body: [
        "هیچ بخشی از این سرویس، از جمله سطح اثر، خلاصه، نمودار قیمت یا هشدار، توصیهٔ خرید، فروش یا نگه‌داشتن دارایی نیست و پیش‌بینی قیمت یا بازار هم نیست. نمودارهای قیمت فقط نشان می‌دهند قیمت پیش و پس از یک رویداد چه بوده است، نه این‌که خبر باعث آن شده یا بعداً چه می‌شود. تصمیم‌های مالی شما با خودتان است؛ در صورت نیاز با مشاور دارای مجوز مشورت کنید.",
      ] },
      { heading: "منابع و حق نشر", body: [[
        "هر خبر به منبع اصلی‌اش نسبت داده می‌شود و پیوند آن نمایش داده می‌شود؛",
        "از برخی منابع (مثلاً رسانه‌های دارای اشتراک پولی یا حساس) فقط واقعیت‌های اصلی را می‌آوریم و برای متن کامل شما را به خود منبع می‌فرستیم؛ متن آن‌ها را بازنشر نمی‌کنیم؛",
        "حق نشر متن و تصویر هر خبر با ناشر اصلی آن است؛",
        "اگر ناشر هستید و می‌خواهید نحوهٔ نمایش خبرهایتان تغییر کند، با ما تماس بگیرید تا اصلاح شود.",
      ]] },
      { heading: "حساب کاربری", body: [
        "برای فهرست پیگیری و هشدار با شمارهٔ موبایل خودتان وارد می‌شوید. شما مسئول دسترسی به همان شماره هستید. هر وقت بخواهید می‌توانید حساب را از صفحهٔ تنظیمات حذف کنید؛ جزئیات در سیاست حریم خصوصی آمده است.",
      ] },
      { heading: "استفادهٔ مجاز", body: [[
        "سرویس را برای استفادهٔ شخصی بخوانید؛",
        "خودکار و انبوه داده برداشت نکنید و فشار غیرعادی به سرور نیاورید؛",
        "برای دور زدن محدودیت‌های ورود یا ارسال کد تلاش نکنید.",
      ]] },
      { heading: "دسترس‌پذیری و تغییرات", body: [
        "سرویس همان‌گونه که هست ارائه می‌شود. ممکن است گاهی در دسترس نباشد، خبری دیر برسد یا هشداری فرستاده نشود؛ برای تصمیم‌های فوری فقط به هشدارها تکیه نکنید. این شرایط ممکن است تغییر کند و تاریخ بالای صفحه نشان می‌دهد آخرین بار کی به‌روز شده است.",
      ] },
    ],
  },
  en: {
    title: "Terms of use",
    sections: [
      { heading: "What this service is", body: [
        "The news radar collects published economic and political news from Iranian and international sources, groups reports of the same event, and estimates how much each event may matter to Iranian investors. Estimates and briefs are produced with the help of AI models and can be wrong or incomplete.",
      ] },
      { heading: "Not investment advice", body: [
        "Nothing in this service, including impact tiers, briefs, price charts or alerts, is a recommendation to buy, sell or hold any asset, and nothing in it is a price or market forecast. Price charts show what prices were before and after an event, not that the news caused the move or what happens next. Your financial decisions are your own; consult a licensed adviser if you need advice.",
      ] },
      { heading: "Sources and copyright", body: [[
        "Every story is attributed to its original source, with a link;",
        "for some sources (for example paywalled or sensitive outlets) we show only the key facts and link out for the full text; we do not republish their copy;",
        "copyright in each story's text and images stays with its publisher;",
        "if you are a publisher and want your stories shown differently, contact us and we will correct it.",
      ]] },
      { heading: "Your account", body: [
        "You sign in with your own mobile number to use watchlists and alerts, and you are responsible for access to that number. You can delete the account at any time from Settings; the privacy policy has the details.",
      ] },
      { heading: "Acceptable use", body: [[
        "read the service for your own use;",
        "do not scrape it in bulk or put unusual load on the server;",
        "do not try to get around the sign-in or code-sending limits.",
      ]] },
      { heading: "Availability and changes", body: [
        "The service is provided as is. It may sometimes be unavailable, news may arrive late, and an alert may not be sent; do not rely on alerts alone for time-critical decisions. These terms may change, and the date at the top of the page shows when they last did.",
      ] },
    ],
  },
};

/** Public: listed in middleware PUBLIC, linked from the footer, the login page and the app. */
export default async function TermsPage() {
  const lang = await language();
  return <LegalPage doc={DOC} lang={lang} updated={UPDATED}
    other={{ href: "/privacy", fa: "سیاست حریم خصوصی", en: "Privacy policy" }} />;
}
