import AnalysisPage from "@/components/AnalysisPage";

export const metadata = { title: "Classification · News Intelligence" };
export const dynamic = "force-dynamic";

export default function ClassificationPage() {
  return <AnalysisPage stage="classification" />;
}
