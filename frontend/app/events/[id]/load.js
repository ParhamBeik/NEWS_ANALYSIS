import { notFound } from "next/navigation";
import { ApiError, apiFetch, apiGet, currentUser } from "@/lib/api";

/** One public event, or the 404 page for a malformed or unknown id.
 *  `allowMissing` returns null instead, for staff looking at a hidden event. */
export async function loadEvent(id, { allowMissing = false } = {}) {
  if (!/^[1-9]\d*$/.test(id)) notFound();
  try { return await apiGet(`/api/public/events/${id}/`); }
  catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      if (allowMissing) return null;
      notFound();
    }
    throw error;
  }
}

/** Takedown state for staff (api/takedown.py); null for everyone else or on any failure. */
export async function loadTakedown(id) {
  if (!/^[1-9]\d*$/.test(id) || !(await currentUser())?.isStaff) return null;
  try {
    const response = await apiFetch(`/api/staff/events/${id}/visibility/`);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}
