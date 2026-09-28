import { useState } from "react";
import { suggestAsk } from "../../api/mattermost";
import type { AskSuggestion } from "../../types";
import { apiErrorMessage } from "../../utils/mattermostAsk";

interface Props {
  question: string;
  onQuestionChange: (value: string) => void;
  onSuggested: (suggestion: AskSuggestion) => void;
  disabled: boolean;
}

/** Free-text description plus a "Suggest" button that drafts the fields. */
export default function AskSuggest({ question, onQuestionChange, onSuggested, disabled }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<string | null>(null);

  const tooShort = question.trim().length < 3;

  async function onSuggest() {
    setBusy(true);
    setError(null);
    setExplanation(null);
    try {
      const suggestion = await suggestAsk(question.trim());
      onSuggested(suggestion);
      setExplanation(suggestion.explanation);
    } catch (err) {
      setError(apiErrorMessage(err, "Suggestion failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ask-suggest">
      <label>
        Describe what you want to pull
        <textarea
          rows={3}
          value={question}
          onChange={(e) => onQuestionChange(e.target.value)}
          placeholder="e.g. Every thread about COSMOS 2589 brightness changes since January"
        />
      </label>
      <button type="button" onClick={onSuggest} disabled={disabled || busy || tooShort}>
        {busy ? "Suggesting..." : "Suggest"}
      </button>
      {error && <div className="form-error">{error}</div>}
      {explanation && (
        <div className="ingest-result">{explanation} Review every field below before saving.</div>
      )}
    </div>
  );
}
