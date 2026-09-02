"use client";
import { useEffect, useState } from "react";

export default function Review() {
  const [cases, setCases] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch("/api/reviews/?limit=30", { credentials: "include" })
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(`${r.status} ${r.statusText}`)))
      .then((data) => setCases(data.results || []))
      .catch((e) => setError(e.message));
  }, []);
  return <main><header><div><p className="eyebrow">HUMAN LABELS</p><h1>Review queue</h1></div><a href="/">Back to feed</a></header>
    {error && <p className="error">{error}</p>}
    <section className="feed">{cases.map((item) => <article className="card" key={item.id}><div><p className="meta">{item.stratum} · {item.status}</p><h3 dir="rtl">{item.article.original_title}</h3><p dir="rtl">{item.article.lead}</p><p className="meta">Use the admin/API form to approve this case.</p></div></article>)}</section>
  </main>;
}
