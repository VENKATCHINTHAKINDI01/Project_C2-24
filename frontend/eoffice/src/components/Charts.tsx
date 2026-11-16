import { useState } from "react";

/** Small SVG charts for the monitoring pad (dataviz method: thin marks, rounded data-ends,
 *  recessive grid, hover tooltips, legend for >= 2 series, colours by role from CSS variables). */

const W = 560;
const H = 180;
const PAD = { l: 40, r: 12, t: 12, b: 26 };

function ticks(max: number): number[] {
  if (max <= 0) return [0];
  const step = Math.pow(10, Math.floor(Math.log10(max)));
  const nice = [1, 2, 5, 10].map((m) => m * step).find((s) => max / s <= 4) ?? step * 10;
  const out: number[] = [];
  for (let v = 0; v <= max + 1e-9; v += nice) out.push(v);
  return out;
}

export interface Bar { label: string; value: number; detail?: string }

export function BarChart({ data, unit = "", title }: { data: Bar[]; unit?: string; title: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.value));
  const ts = ticks(max);
  const top = ts[ts.length - 1] || 1;
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const slot = iw / Math.max(1, data.length);
  const bw = Math.max(4, Math.min(28, slot - 6));
  const y = (v: number) => PAD.t + ih - (v / top) * ih;
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {ts.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="grid-line" />
            <text x={PAD.l - 6} y={y(t) + 4} className="tick" textAnchor="end">{t}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = PAD.l + i * slot + (slot - bw) / 2;
          const h = Math.max(0, y(0) - y(d.value));
          const r = Math.min(4, bw / 2, h);
          return (
            <g key={d.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={PAD.l + i * slot} y={PAD.t} width={slot} height={ih} fill="transparent" />
              <path className={`bar${hover === i ? " on" : ""}`}
                d={`M${x},${y(0)} V${y(0) - h + r} Q${x},${y(0) - h} ${x + r},${y(0) - h} H${x + bw - r} Q${x + bw},${y(0) - h} ${x + bw},${y(0) - h + r} V${y(0)} Z`} />
              {(data.length <= 14 || i % Math.ceil(data.length / 10) === 0) && (
                <text x={x + bw / 2} y={H - 8} className="tick" textAnchor="middle">{d.label}</text>
              )}
            </g>
          );
        })}
      </svg>
      {hover !== null && data[hover] && (
        <div className="chart-tip" style={{ left: `${((PAD.l + (hover + 0.5) * slot) / W) * 100}%` }}>
          <strong>{data[hover].label}</strong> {data[hover].value}{unit}
          {data[hover].detail && <div>{data[hover].detail}</div>}
        </div>
      )}
      {data.length === 0 && <p className="muted empty">No data in this window.</p>}
    </figure>
  );
}

export interface Series { name: string; cls: string; values: (number | null)[] }

export function LineChart({ labels, series, unit = "", title }: {
  labels: string[]; series: Series[]; unit?: string; title: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...series.flatMap((s) => s.values.filter((v): v is number => v !== null)));
  const ts = ticks(max);
  const top = ts[ts.length - 1] || 1;
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (labels.length <= 1 ? iw / 2 : (i / (labels.length - 1)) * iw);
  const y = (v: number) => PAD.t + ih - (v / top) * ih;
  const near = (px: number) => {
    let best = 0;
    labels.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i; });
    return best;
  };
  return (
    <figure className="chart">
      <figcaption>{title}
        <span className="legend">{series.map((s) => <span key={s.name} className={`key ${s.cls}`}>{s.name}</span>)}</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          setHover(near(((e.clientX - r.left) / r.width) * W));
        }}
        onMouseLeave={() => setHover(null)}>
        {ts.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="grid-line" />
            <text x={PAD.l - 6} y={y(t) + 4} className="tick" textAnchor="end">{t}</text>
          </g>
        ))}
        {labels.map((l, i) => (labels.length <= 14 || i % Math.ceil(labels.length / 10) === 0) && (
          <text key={l} x={x(i)} y={H - 8} className="tick" textAnchor="middle">{l}</text>
        ))}
        {hover !== null && <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + ih} />}
        {series.map((s) => {
          const pts = s.values.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean);
          return (
            <g key={s.name} className={`series ${s.cls}`}>
              <polyline points={pts.join(" ")} />
              {s.values.map((v, i) => v !== null && (labels.length <= 31 || hover === i) && (
                <circle key={i} cx={x(i)} cy={y(v)} r={hover === i ? 4.5 : 3} />
              ))}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div className="chart-tip" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <strong>{labels[hover]}</strong>
          {series.map((s) => <div key={s.name}><span className={`key ${s.cls}`} />{s.name}: {s.values[hover] ?? "—"}{unit}</div>)}
        </div>
      )}
      {labels.length === 0 && <p className="muted empty">No data in this window.</p>}
    </figure>
  );
}

/** A labelled horizontal bar list: categories and their share (identity carried by the label). */
export function ShareList({ items, title }: { items: [string, number][]; title: string }) {
  const total = items.reduce((a, [, n]) => a + n, 0) || 1;
  return (
    <figure className="chart share">
      <figcaption>{title}</figcaption>
      <ul>
        {items.map(([k, n]) => (
          <li key={k} title={`${k}: ${n} (${Math.round((n / total) * 100)}%)`}>
            <span className="lbl">{k}</span>
            <span className="track"><span className="fill" style={{ width: `${(n / total) * 100}%` }} /></span>
            <span className="num">{n}</span>
          </li>
        ))}
      </ul>
      {items.length === 0 && <p className="muted empty">No data in this window.</p>}
    </figure>
  );
}
