import type { Application } from "../types";

interface ScoreHistogramCardProps {
  applications: Application[];
}

const BUCKETS = [
  { label: "0–2", min: 0, max: 2, shortlistedZone: false, color: "#FF2A6D" },
  { label: "2–4", min: 2, max: 4, shortlistedZone: false, color: "var(--solid-bg)" },
  { label: "4–6", min: 4, max: 6, shortlistedZone: false, color: "#05D9E8" },
  { label: "6–8", min: 6, max: 8, shortlistedZone: true, color: "#B8F200" },
  { label: "8–10", min: 8, max: 10.01, shortlistedZone: true, color: "#2E7D32" },
];

export function ScoreHistogramCard({ applications }: ScoreHistogramCardProps) {
  const scored = applications.filter(
    (a) => a.status === "completed" && a.score_out_of_10 !== null
  );

  const counts = BUCKETS.map((b) =>
    scored.filter((a) => {
      const s = a.score_out_of_10 ?? 0;
      return s >= b.min && s < b.max;
    }).length
  );

  const maxCount = Math.max(1, ...counts);
  const totalClaims = applications.reduce((acc, a) => acc + (a.claims?.length ?? 0), 0);
  const verifiedClaims = applications.reduce(
    (acc, a) => acc + (a.claims?.filter((c) => c.verification_status === "verified").length ?? 0),
    0
  );
  const verifiedRatio = totalClaims > 0 ? verifiedClaims / totalClaims : 0;
  const filledSegments = Math.round(verifiedRatio * 10);

  return (
    <section className="wire-card flex h-full flex-col justify-between p-5 sm:p-6">
      <div>
        <span className="sui-spec-label text-[var(--ink-primary)]">[SCORE DISTRIBUTION · /10]</span>
        <h2 className="display-heading mt-1.5 text-lg font-bold text-[var(--ink-primary)]">
          Score Distribution
        </h2>
      </div>

      <div className="mt-5 grid h-28 grid-cols-5 items-end gap-2.5 border-b border-[var(--border-heavy)] pb-2">
        {BUCKETS.map((bucket, idx) => {
          const count = counts[idx];
          const heightPct =
            scored.length === 0
              ? (idx + 1) * 14
              : Math.max(14, Math.round((count / maxCount) * 100));
          const isPlaceholder = scored.length === 0;
          return (
            <div key={bucket.label} className="flex h-full flex-col items-center justify-end gap-1.5">
              <span className="sui-spec-label tabular-nums text-[10px] text-[var(--ink-primary)]">
                {isPlaceholder ? "—" : count}
              </span>
              <div
                title={`${bucket.label} pts: ${count} candidate(s)`}
                style={{
                  height: `${heightPct}%`,
                  backgroundColor: isPlaceholder ? "var(--surface-subtle)" : bucket.color,
                }}
                className="w-full border border-[var(--border-card)]"
              />
            </div>
          );
        })}
      </div>

      <div className="mt-2 grid grid-cols-5 gap-2.5 text-center">
        {BUCKETS.map((b) => (
          <span
            key={b.label}
            className={`sui-spec-label tabular-nums ${
              b.shortlistedZone
                ? "wire-tag-solid px-1 py-0.5"
                : "text-[var(--ink-primary)]"
            }`}
          >
            {b.label}
          </span>
        ))}
      </div>

      {/* 2px Framed Segmented Claim Meter */}
      <div className="mt-4 space-y-2 border-t border-[var(--divider-rule)] pt-3">
        <div
          aria-label="Claims verified ratio"
          className="grid h-3 w-full grid-cols-10 divide-x divide-[var(--border-heavy)] border-2 border-[var(--border-heavy)] bg-[var(--surface-bg)]"
        >
          {Array.from({ length: 10 }, (_, idx) => (
            <div
              key={idx}
              style={{
                backgroundColor: idx < filledSegments ? "#2E7D32" : "var(--surface-subtle)",
              }}
            />
          ))}
        </div>

        <div className="flex items-center justify-between text-xs">
          <span className="sui-spec-label text-[var(--ink-primary)]">
            CLAIMS VERIFIED: <strong>{verifiedClaims}/{totalClaims}</strong>
          </span>
          <span className="sui-spec-label wire-tag px-1.5 py-0.5">
            THRESHOLD ≥ 6.0
          </span>
        </div>
      </div>
    </section>
  );
}
