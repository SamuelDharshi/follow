"use client";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { timeLabel } from "@/lib/api";

export type Series = { key: string; label: string; color: string };

export default function Chart({
  data,
  series,
  fmt,
  log,
  signed,
}: {
  data: Record<string, number | null>[];
  series: Series[];
  fmt: (v: number) => string;
  log?: boolean;
  signed?: boolean;
}) {
  if (!data.length) return <div className="empty">No data in this range yet.</div>;
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="t" tickFormatter={timeLabel} stroke="var(--muted)" fontSize={11} minTickGap={48} />
          <YAxis
            stroke="var(--muted)"
            fontSize={11}
            width={64}
            tickFormatter={fmt}
            scale={log ? "log" : "auto"}
            domain={log || signed ? ["auto", "auto"] : [0, "auto"]}
            allowDataOverflow
          />
          <Tooltip
            labelFormatter={(t) => timeLabel(Number(t))}
            formatter={(v) => fmt(Number(v))}
            contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }}
          />
          {series.length > 1 && <Legend />}
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              dot={false}
              strokeWidth={2}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
