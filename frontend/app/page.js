"use client";

import { useEffect, useState } from "react";

async function getJSON(path) {
  const response = await fetch(path, { credentials: "include", cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

export default function Home() {
  const [kpi, setKpi] = useState(null);
  const [articles, setArticles] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getJSON("/api/kpi/"), getJSON("/api/articles/?limit=30")])
      .then(([summary, feed]) => { setKpi(summary); setArticles(feed.results || []); })
      .catch((err) => setError(err.message));
  }, []);

  return (
    <main>
      <header><div><p className="eyebrow">NEWS INTELLIGENCE</p><h1>Analyst feed</h1></div><a href="/admin/">Sign in</a></header>
      {error && <p className="error">Authentication or API error: {error}</p>}
      {kpi && <section className="metrics">{[
        ["Articles", kpi.articles], ["Classified", kpi.classified], ["Evaluated", kpi.evaluated],
        ["Pending review", kpi.review_pending], ["A/B feedback", kpi.ab_feedback]
      ].map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</section>}
      <section className="feed">
        <div className="section-heading"><h2>Latest stories</h2><nav><a href="/review">Review</a><a href="/ab">A/B lab</a></nav></div>
        {articles.map((article) => <article className="card" key={article.id}>
          {article.image_url && <img src={article.image_url} alt="" />}
          <div><p className="meta">{article.source_name || article.source} · {article.published_at_jalali || "undated"}</p>
            <h3 dir="rtl">{article.summary?.optimized_title || article.original_title}</h3>
            <p dir="rtl">{article.summary?.one_line || article.lead}</p>
            <div className="tags">{article.classification && <span>{article.classification.category}</span>}{article.evaluation?.gold_trend && <span>{article.evaluation.gold_trend}</span>}</div>
          </div>
        </article>)}
      </section>
    </main>
  );
}
