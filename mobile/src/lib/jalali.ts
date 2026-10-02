/**
 * Jalali dates and Persian digits without Intl.
 *
 * Hermes ships only a partial Intl on Android, and the `persian` calendar and IANA time
 * zones are exactly the parts it may lack, so the conversion is done by hand. Tehran has
 * had a fixed UTC+03:30 offset since Iran abolished daylight saving in 2022; dates before
 * that may read one hour early in summer, which a 48-hour news radar never shows.
 */

export type Lang = "fa" | "en";

const TEHRAN_OFFSET_MS = 210 * 60 * 1000;

const MONTHS_FA = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
const MONTHS_EN = ["Farvardin", "Ordibehesht", "Khordad", "Tir", "Mordad", "Shahrivar", "Mehr", "Aban", "Azar", "Dey", "Bahman", "Esfand"];
const GREGORIAN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS_BEFORE_MONTH = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];

/** Gregorian Y-M-D (month 1-12) to Jalali [year, month 1-12, day]. 33-year-cycle arithmetic. */
export function toJalali(gy: number, gm: number, gd: number): [number, number, number] {
  const gy2 = gm > 2 ? gy + 1 : gy;
  let days = 355666 + 365 * gy + Math.floor((gy2 + 3) / 4) - Math.floor((gy2 + 99) / 100)
    + Math.floor((gy2 + 399) / 400) + gd + DAYS_BEFORE_MONTH[gm - 1];
  let jy = -1595 + 33 * Math.floor(days / 12053);
  days %= 12053;
  jy += 4 * Math.floor(days / 1461);
  days %= 1461;
  if (days > 365) {
    jy += Math.floor((days - 1) / 365);
    days = (days - 1) % 365;
  }
  return days < 186
    ? [jy, 1 + Math.floor(days / 31), 1 + (days % 31)]
    : [jy, 7 + Math.floor((days - 186) / 30), 1 + ((days - 186) % 30)];
}

export function faDigits(value: string | number): string {
  return String(value).replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
}

export function localDigits(value: string | number, lang: Lang): string {
  return lang === "fa" ? faDigits(value) : String(value);
}

/** Tehran wall clock as UTC fields of a shifted Date, or null for a missing/invalid time. */
function tehran(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const time = new Date(iso).getTime();
  return Number.isNaN(time) ? null : new Date(time + TEHRAN_OFFSET_MS);
}

const pad = (value: number) => String(value).padStart(2, "0");

/** "۱۰ مهر ۱۴۰۵، ۰۰:۳۰" / "10 Mehr 1405, 00:30" in Tehran time; "—" when missing. */
export function formatJalali(iso: string | null | undefined, lang: Lang = "fa", { time = true } = {}): string {
  const date = tehran(iso);
  if (!date) return "—";
  const [jy, jm, jd] = toJalali(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
  const day = `${jd} ${(lang === "fa" ? MONTHS_FA : MONTHS_EN)[jm - 1]} ${jy}`;
  const text = time ? `${day}${lang === "fa" ? "، " : ", "}${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}` : day;
  return localDigits(text, lang);
}

/** Secondary Gregorian date, always Latin digits: "2 Oct 2026". */
export function formatGregorian(iso: string | null | undefined): string {
  const date = tehran(iso);
  if (!date) return "";
  return `${date.getUTCDate()} ${GREGORIAN[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}
