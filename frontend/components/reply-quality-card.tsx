import type { Usage } from "@/lib/types";

const REPLY_STATUSES = [
  { key: "answer", label: "Answered" },
  { key: "clarify", label: "Clarified" },
  { key: "unknown", label: "No data" },
] as const;

type ReplyQualityCardProps = {
  byStatus: NonNullable<Usage["by_status"]>;
};

/** How often the assistant answered outright versus asked one question or reported missing data. */
export function ReplyQualityCard({ byStatus }: ReplyQualityCardProps) {
  const answered = byStatus.answer ?? 0;
  const clarified = byStatus.clarify ?? 0;
  const total = answered + clarified + (byStatus.unknown ?? 0);
  const clarifyRate = total === 0 ? 0 : Math.round((clarified / total) * 100);

  return (
    <section className="v-card" aria-labelledby="reply-quality-title">
      <div className="v-card-head">
        <h2 id="reply-quality-title">Reply Quality</h2>
        <span className="v-muted">All time</span>
      </div>
      <div className="v-status-grid">
        {REPLY_STATUSES.map((entry) => (
          <div className="v-status-cell" key={entry.key}>
            <strong>{byStatus[entry.key] ?? 0}</strong>
            <span>{entry.label}</span>
          </div>
        ))}
        <div className="v-status-cell is-emphasis">
          <strong>{clarifyRate}%</strong>
          <span>Clarify rate</span>
        </div>
      </div>
      <p className="v-card-sub">
        Clarify means the assistant asked one question instead of guessing; unknown means the
        data was missing.
      </p>
    </section>
  );
}
