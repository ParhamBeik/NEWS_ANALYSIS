import { Skeleton } from "@/components/AsyncPanel";

/**
 * Shown while a route segment's data resolves, for every page that does not define its own.
 *
 * This is what makes navigation feel immediate on the single-fetch dashboards (`/ops`,
 * `/kpi`, `/market`, `/exports`). Those pages await one endpoint and there is nothing
 * useful to split them into, so the fix is not to restructure them - it is to stop the
 * browser sitting on the previous page with no feedback while the new one is fetched.
 * The navigation commits instantly and the layout chrome stays interactive.
 */
export default function Loading() {
  return (
    <div>
      <Skeleton className="mb-2 h-8 w-56" />
      <Skeleton className="mb-6 h-4 w-96 max-w-full" />
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <Skeleton key={index} className="h-[86px]" />
        ))}
      </div>
      <div className="grid gap-3">
        {[0, 1, 2, 3].map((index) => (
          <Skeleton key={index} className="h-24" />
        ))}
      </div>
    </div>
  );
}
