import { useState } from "react";
import { searchMattermostPeople } from "../../api/mattermost";
import type { MattermostPerson } from "../../types";
import { apiErrorMessage } from "../../utils/mattermostAsk";

interface Props {
  onAdd: (username: string) => void;
}

function personLabel(person: MattermostPerson): string {
  const extra = [person.name, person.nickname].filter(Boolean).join(", ");
  return extra ? `@${person.username} (${extra})` : `@${person.username}`;
}

/** Find a Mattermost username from a name and add it to the authors list. */
export default function AuthorLookup({ onAdd }: Props) {
  const [query, setQuery] = useState("");
  const [people, setPeople] = useState<MattermostPerson[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = query.trim();

  async function onFind() {
    if (trimmed.length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const found = await searchMattermostPeople(trimmed);
      setPeople(found.filter((p) => p.username));
    } catch (err) {
      setError(apiErrorMessage(err, "Person lookup failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ask-lookup">
      <label>
        Find person (name, at least 2 characters)
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onFind();
            }
          }}
          placeholder="e.g. Smith"
        />
      </label>
      <button type="button" onClick={onFind} disabled={busy || trimmed.length < 2}>
        {busy ? "Finding..." : "Find person"}
      </button>
      {error && <div className="form-error">{error}</div>}
      {people && people.length === 0 && <p className="muted">No matching people.</p>}
      {people && people.length > 0 && (
        <ul className="ask-lookup-results">
          {people.map((p) => (
            <li key={p.username}>
              <button type="button" onClick={() => onAdd(p.username ?? "")}>
                Add {personLabel(p)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
