/**
 * Phone sign-in form rules, mirrored from backend/core/otp.py so the app refuses a bad number
 * before spending one of the five hourly codes. The server stays the authority. Pure.
 */
import type { Lang } from "./jalali";

/** Matches core.otp.RESEND_SECONDS: the server refuses a second code inside this window. */
export const RESEND_SECONDS = 60;
export const CODE_LENGTH = 6;

const LOCAL_DIGITS: Record<string, string> = {
  "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
  "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
};

export const asciiDigits = (raw: string) => raw.replace(/[۰-۹٠-٩]/g, (digit) => LOCAL_DIGITS[digit]);

/**
 * Canonical +989xxxxxxxxx, or null. Accepts 0912..., 912..., +98912..., 0098912... with
 * Persian/Arabic digits, spaces and dashes, the same forms core.otp.normalize_phone accepts.
 */
export function normalizePhone(raw: string | null | undefined): string | null {
  let digits = asciiDigits(String(raw ?? "")).replace(/[\s\-()]/g, "");
  for (const prefix of ["+98", "0098", "98", "0"]) {
    if (digits.startsWith(prefix) && digits.length - prefix.length === 10) {
      digits = digits.slice(prefix.length);
      break;
    }
  }
  return /^9\d{9}$/.test(digits) ? `+98${digits}` : null;
}

/** "+989121234567" -> "0912 123 4567" for display. */
export function displayPhone(phone: string): string {
  const local = `0${phone.replace(/^\+98/, "")}`;
  return `${local.slice(0, 4)} ${local.slice(4, 7)} ${local.slice(7)}`;
}

/** The six-digit code with Persian digits folded to ASCII, or null while incomplete. */
export function cleanCode(raw: string): string | null {
  const code = asciiDigits(raw).replace(/\s/g, "");
  return new RegExp(`^\\d{${CODE_LENGTH}}$`).test(code) ? code : null;
}

/** Whole seconds until another code may be requested; 0 when it may. */
export function resendIn(sentAt: number | null, now = Date.now(), wait = RESEND_SECONDS): number {
  if (sentAt == null) return 0;
  return Math.max(0, Math.ceil((sentAt + wait * 1000 - now) / 1000));
}

/** Same wording as the web login (frontend/app/login/actions.js OTP_MESSAGES). */
const OTP_MESSAGES: Record<string, [string, string]> = {
  invalid_phone: ["Enter an Iranian mobile number, e.g. 0912 123 4567.", "شمارهٔ موبایل را درست وارد کنید؛ مثلاً ۰۹۱۲۱۲۳۴۵۶۷."],
  invalid_code: ["That code is wrong or has expired.", "کد نادرست است یا منقضی شده است."],
  too_soon: ["A code was just sent. Wait a minute before asking again.", "کد همین الان فرستاده شد؛ یک دقیقه صبر کنید."],
  too_many: ["Too many codes for this number. Try again in an hour.", "برای این شماره کد زیادی درخواست شده؛ یک ساعت دیگر دوباره امتحان کنید."],
  account_disabled: ["This account is disabled.", "این حساب غیرفعال است."],
  sms_unavailable: ["SMS sign-in is not available yet.", "ورود با پیامک هنوز فعال نیست."],
  throttled: ["Too many attempts. Please wait before trying again.", "تلاش‌ها زیاد بوده؛ کمی بعد دوباره امتحان کنید."],
  network: ["Cannot reach the server.", "اتصال به سرور برقرار نشد."],
};

/** A refusal to show. `code` is the API's `error`, "throttled" for a bare 429, or "network". */
export function otpMessage(code: string | null | undefined, lang: Lang): string {
  const [en, fa] = OTP_MESSAGES[code ?? ""] ?? ["Sign-in failed. Try again.", "ورود انجام نشد؛ دوباره امتحان کنید."];
  return lang === "fa" ? fa : en;
}

/** Map a thrown error from requestCode/verifyCode to an OTP_MESSAGES key. */
export function otpReason(error: unknown): string {
  const err = error as { status?: number; code?: string | null } | null;
  if (!err || typeof err.status !== "number") return "network";
  if (err.code) return err.code;
  return err.status === 429 ? "throttled" : "unknown";
}
