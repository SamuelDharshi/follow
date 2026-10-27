"use client";
import { useEffect, useState } from "react";
import PageHero from "@/components/PageHero";
import { API, TUNNEL_HEADERS, getJson, timeLabel } from "@/lib/api";

type File = { name: string; bytes: number; modified: number; url: string };

export default function Data() {
  const [files, setFiles] = useState<File[] | null>(null);
  const [schema, setSchema] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    getJson<{ files: File[] }>("/api/dataset").then((d) => setFiles(d.files)).catch((e) => setErr(e.message));
    fetch(`${API}/api/dataset/schema`, { headers: TUNNEL_HEADERS }).then((r) => r.text()).then(setSchema).catch(() => {});
  }, []);
  const mb = (b: number) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e3).toFixed(0)} kB`);
  return (
    <>
      <PageHero title="Dataset" sub="Every recorded event and sample as Parquet, with every outage marked. Plus a read-only API." seed={13} />
      <div className="app-body">
      <h1>Open dataset</h1>
      <p className="sub">Everything the recorder stored, as Parquet files split by table and UTC day. Gaps are in <code>gaps.parquet</code>; analysing across a gap without checking it will give wrong answers.</p>
      {err && <div className="empty err">Could not load the file list: {err}</div>}
      {!files && !err && <div className="empty">Loading…</div>}
      {files && !files.length && <div className="empty">Export is being built (it refreshes every 15 minutes). Check back shortly.</div>}
      {files && files.length > 0 && (
        <div className="tablewrap">
          <table>
            <thead><tr><th>File</th><th>Size</th><th>Updated</th></tr></thead>
            <tbody>{files.map((f) => (
              <tr key={f.name}><td><a href={`${API}${f.url}`}>{f.name}</a></td><td>{mb(f.bytes)}</td><td>{timeLabel(f.modified)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <h2>Query the metrics</h2>
      <p className="prose">
        Read-only endpoint: <code>GET {API}/api/query?start=&lt;unix ms&gt;&amp;end=&lt;unix ms&gt;&amp;step=minute|hour|day</code>.
        Interactive docs at <a href={`${API}/docs`}>{API}/docs</a>.
      </p>
      <h2>Schema</h2>
      <pre className="prose small" style={{ whiteSpace: "pre-wrap" }}>{schema || "Schema unavailable."}</pre>
      </div>
    </>
  );
}
