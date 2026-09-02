"use client";
import { useEffect, useState } from "react";

export default function AB() {
  const [pairs, setPairs] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch("/api/ab/pairs/?limit=30", { credentials: "include" })
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(`${r.status} ${r.statusText}`)))
      .then((data) => setPairs(data.results || []))
      .catch((e) => setError(e.message));
  }, []);
  return <main><header><div><p className="eyebrow">MODEL EXPERIMENTS</p><h1>A/B lab</h1></div><a href="/">Back to feed</a></header>
    {error && <p className="error">{error}</p>}
    <section className="feed">{pairs.map((pair) => <article className="card" key={pair.id}><div><p className="meta">Pair {pair.id}</p><h3 dir="rtl">{pair.article}</h3><div className="metrics"><div className="metric"><span>Left</span><strong dir="rtl">{pair.left.one_line || "No summary"}</strong></div><div className="metric"><span>Right</span><strong dir="rtl">{pair.right.one_line || "No summary"}</strong></div></div><p className="meta">Feedback is stored through POST /api/ab/pairs/{pair.id}/feedback/.</p></div></article>)}</section>
  </main>;
}
