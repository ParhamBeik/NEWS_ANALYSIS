import { Card, EmptyState, SectionTitle, TableScroll } from "@/components/primitives";
import { apiGet } from "@/lib/api";
import { tehranTime } from "@/lib/display";

export const metadata = { title: "Exports · News Intelligence" };
export const dynamic = "force-dynamic";

function size(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default async function ExportsPage() {
  const files = await apiGet("/api/exports/");

  return (
    <>
      <h1 className="mb-1 text-2xl font-semibold text-slate-100">Exports</h1>
      <p className="mb-6 text-sm text-slate-500">
        Download the team&rsquo;s Persian analyst workbook and category feeds. New files are
        prepared nightly at 23:50 Tehran time.
      </p>

      {files.length === 0 ? (
        <EmptyState title="No workbooks yet.">
          The next scheduled export will appear here after it completes.
        </EmptyState>
      ) : (
        <Card className="p-4">
          <SectionTitle hint={`${files.length} file${files.length === 1 ? "" : "s"}`}>
            Available
          </SectionTitle>
          <TableScroll>
            <table className="w-full min-w-[280px] text-sm">
            <tbody>
              {files.map((file) => (
                <tr key={file.name} className="border-t border-slate-800">
                  <td className="py-2">
                    {/* A plain anchor, not next/link: this is a file download that must go
                        through the browser's own handling, not the client router. */}
                    <a
                      href={`/exports/download/${file.name
                        .split("/")
                        .map(encodeURIComponent)
                        .join("/")}`}
                      className="text-emerald-400 hover:underline"
                      download
                    >
                      {file.name}
                    </a>
                  </td>
                  <td className="py-2 text-right tabular text-slate-500">
                    {size(file.size_bytes)}
                  </td>
                  <td className="py-2 text-right text-xs text-slate-500">
                    {tehranTime(file.modified_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableScroll>
        </Card>
      )}
    </>
  );
}
