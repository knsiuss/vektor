import type { FeedbackItem } from "@/lib/types";

import { Info } from "./icons";

function formatWhen(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

export function FeedbackPanel({ items }: { items: FeedbackItem[] }) {
  const downvoted = items.filter((item) => item.rating === "down");

  return (
    <section className="v-card" aria-labelledby="feedback-title">
      <div className="v-card-head">
        <h2 id="feedback-title">Answers To Review</h2>
        {downvoted.length > 0 && (
          <span className="v-muted">{downvoted.length} downvoted</span>
        )}
      </div>
      {downvoted.length === 0 ? (
        <div className="v-empty">
          <Info size={26} aria-hidden="true" />
          <p>No downvoted answers yet.</p>
          <span>
            Use the thumbs-down button on an answer and it will show up here with the text
            it referred to.
          </span>
        </div>
      ) : (
        <ul className="v-feedback-list">
          {downvoted.map((item) => (
            <li className="v-feedback-row" key={item.id}>
              <div className="v-feedback-body">
                <p className="v-feedback-excerpt">{item.excerpt || "(empty answer)"}</p>
                {item.comment && <p className="v-feedback-comment">“{item.comment}”</p>}
                <p className="v-feedback-meta">
                  {item.conversation_title ?? "Untitled session"} · {formatWhen(item.created_at)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
