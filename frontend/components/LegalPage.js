import Link from "next/link";

/**
 * A legal text in both languages on one page: the reader's language first, the other below,
 * each with its own `lang`/`dir`. Persian is the primary text; the app opens these URLs
 * without a language cookie, so it lands on Persian.
 *
 * `doc` is { fa: { title, sections }, en: { title, sections } }; a section is
 * { heading, body: [paragraph | [list items]] }.
 */
export default function LegalPage({ doc, lang, updated, other }) {
  const order = lang === "en" ? ["en", "fa"] : ["fa", "en"];
  return <div className="mx-auto max-w-3xl space-y-12 pb-12">
    {order.map((code, index) => {
      const text = doc[code];
      const fa = code === "fa";
      return <article key={code} id={code} lang={code} dir={fa ? "rtl" : "ltr"} className="space-y-6">
        <header className="space-y-2">
          <h1 className="text-3xl font-extrabold">{text.title}</h1>
          <p className="text-sm text-muted">{fa ? `آخرین به‌روزرسانی: ${updated.fa}` : `Last updated: ${updated.en}`}</p>
          {index === 0 ? <p className="text-sm">
            <a href={`#${order[1]}`} className="text-accent underline underline-offset-4"
              lang={fa ? "en" : "fa"} dir={fa ? "ltr" : "rtl"}>
              {fa ? "English version below" : "نسخهٔ فارسی در ادامه"}
            </a>
          </p> : null}
        </header>
        {text.sections.map((section) => <section key={section.heading} className="space-y-3">
          <h2 className="text-xl font-bold">{section.heading}</h2>
          {section.body.map((block, blockIndex) => Array.isArray(block)
            ? <ul key={blockIndex} className="list-disc space-y-1 ps-6 leading-8">{block.map((item) => <li key={item}>{item}</li>)}</ul>
            : <p key={blockIndex} className="leading-8">{block}</p>)}
        </section>)}
        <p className="text-sm">
          <Link href={other.href} className="text-accent underline underline-offset-4">{other[code]}</Link>
        </p>
      </article>;
    })}
  </div>;
}
