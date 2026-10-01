import { notFound } from "next/navigation";
import { ApiError, apiGet } from "@/lib/api";

/** One public event, or the 404 page for a malformed or unknown id. */
export async function loadEvent(id) {
  if (!/^[1-9]\d*$/.test(id)) notFound();
  try { return await apiGet(`/api/public/events/${id}/`); }
  catch (error) { if (error instanceof ApiError && error.status === 404) notFound(); throw error; }
}
