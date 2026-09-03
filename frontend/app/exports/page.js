import { Card, EmptyState, SectionTitle } from "@/components/primitives";
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
        The team&rsquo;s Persian analyst workbook, built by a scheduled task at 23:50 Tehran
        time and kept byte-compatible with the template — including the{" "}
        <code className="text-slate-400">extLst</code> block openpyxl drops, which is what
        the dropdown validations live in.
      </p>

      {files.length === 0 ? (
        <EmptyState title="No workbooks yet.">
          The exporter runs nightly. Trigger one manually with{" "}
          <code>manage.py build_workbook</code>.
        </EmptyState>
      ) : (
        <Card className="p-4">
          <SectionTitle hint={`${files.length} file${files.length === 1 ? "" : "s"}`}>
            Available
          </SectionTitle>
          <table className="w-full text-sm">
            <tbody>
              {files.map((file) => (
                <tr key={file.name} className="border-t border-slate-800">
                  <td className="py-2">
                    {/* A plain anchor, not next/link: this is a file download that must go
                        through the browser's own handling, not the client router. */}
                    <a
                      href={`/exports/download/${encodeURIComponent(file.name)}`}
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
        </Card>
      )}
    </>
  );
}
