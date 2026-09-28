import { FormEvent, useState } from "react";
import { createAsk, updateAsk } from "../../api/mattermost";
import type { Ask, AskExtractSource, AskSuggestion, MattermostChannel } from "../../types";
import {
  apiErrorLines,
  appendToList,
  applySuggestion,
  askToForm,
  AskFormState,
  emptyAskForm,
  formToPayload,
  MAX_REFRESH_MINUTES,
  MIN_REFRESH_MINUTES,
  SCOPE_OPTIONS,
} from "../../utils/mattermostAsk";
import AskSuggest from "./AskSuggest";
import AuthorLookup from "./AuthorLookup";

interface Props {
  initial: Ask | null;
  channels: MattermostChannel[];
  onSaved: (ask: Ask) => void;
  onCancel: () => void;
}

interface ListFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

function ListField({ label, value, onChange, placeholder }: ListFieldProps) {
  return (
    <label>
      {label}
      <textarea
        rows={3}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </label>
  );
}

function channelOptionLabel(channel: MattermostChannel): string {
  const base = channel.display_name ? `${channel.display_name} (${channel.name})` : channel.name;
  return channel.archived ? `${base}, archived` : base;
}

export default function AskForm({ initial, channels, onSaved, onCancel }: Props) {
  const [form, setForm] = useState<AskFormState>(() =>
    initial ? askToForm(initial) : emptyAskForm(),
  );
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  function set<K extends keyof AskFormState>(key: K, value: AskFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function onSuggested(suggestion: AskSuggestion) {
    setForm((current) => applySuggestion(current, suggestion));
    setErrors([]);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const result = formToPayload(form);
    if (!result.payload) {
      setErrors(result.errors);
      return;
    }
    setSaving(true);
    setErrors([]);
    try {
      const saved = initial
        ? await updateAsk(initial.id, result.payload)
        : await createAsk(result.payload);
      onSaved(saved);
    } catch (err) {
      setErrors(apiErrorLines(err, "Save failed."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card">
      <h2>{initial ? `Edit ask: ${initial.name}` : "New ask"}</h2>
      <AskSuggest
        question={form.question}
        onQuestionChange={(v) => set("question", v)}
        onSuggested={onSuggested}
        disabled={saving}
      />

      <form onSubmit={onSubmit} className="ask-form">
        <label>
          Name
          <input type="text" value={form.name} onChange={(e) => set("name", e.target.value)} />
        </label>

        <div className="ask-form-grid">
          <ListField
            label="Terms (all must appear)"
            value={form.terms}
            onChange={(v) => set("terms", v)}
            placeholder="One per line or comma separated"
          />
          <ListField
            label="Any of these terms (at least one must appear)"
            value={form.anyTerms}
            onChange={(v) => set("anyTerms", v)}
            placeholder="One per line or comma separated"
          />
          <div>
            <ListField
              label="Authors (Mattermost usernames)"
              value={form.authors}
              onChange={(v) => set("authors", v)}
              placeholder="e.g. jsmith"
            />
            <AuthorLookup onAdd={(u) => set("authors", appendToList(form.authors, u))} />
          </div>
          <div>
            <ListField
              label="Channels (URL names, empty means all channels)"
              value={form.channels}
              onChange={(v) => set("channels", v)}
              placeholder="e.g. sda-ops"
            />
            <label>
              Add a channel
              <select
                value=""
                onChange={(e) => set("channels", appendToList(form.channels, e.target.value))}
              >
                <option value="">Choose a channel</option>
                {channels.map((c) => (
                  <option key={c.id} value={c.name}>
                    {channelOptionLabel(c)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="ask-form-row">
          <label>
            After (date)
            <input type="date" value={form.after} onChange={(e) => set("after", e.target.value)} />
          </label>
          <label>
            Before (date)
            <input
              type="date"
              value={form.before}
              onChange={(e) => set("before", e.target.value)}
            />
          </label>
          <label>
            Refresh every (minutes, {MIN_REFRESH_MINUTES} to {MAX_REFRESH_MINUTES}; empty means only
            when asked)
            <input
              type="number"
              min={MIN_REFRESH_MINUTES}
              max={MAX_REFRESH_MINUTES}
              value={form.refreshMinutes}
              onChange={(e) => set("refreshMinutes", e.target.value)}
            />
          </label>
        </div>

        <label className="ask-checkbox">
          <input
            type="checkbox"
            checked={form.includeArchived}
            onChange={(e) => set("includeArchived", e.target.checked)}
          />
          Include archived (closed) channels
        </label>

        <fieldset className="ask-fieldset">
          <legend>Scope</legend>
          {SCOPE_OPTIONS.map((option) => (
            <label key={option.value} className="ask-checkbox">
              <input
                type="radio"
                name="ask-scope"
                value={option.value}
                checked={form.scope === option.value}
                onChange={() => set("scope", option.value)}
              />
              {option.label}
            </label>
          ))}
        </fieldset>

        <fieldset className="ask-fieldset">
          <legend>Extract a value (regular expression, first group kept)</legend>
          <div className="ask-form-row">
            <label>
              Pattern (optional)
              <input
                type="text"
                value={form.extractPattern}
                onChange={(e) => set("extractPattern", e.target.value)}
                placeholder="e.g. NORAD (\d+)"
              />
            </label>
            <label>
              Read from
              <select
                value={form.extractSource}
                onChange={(e) => set("extractSource", e.target.value as AskExtractSource)}
              >
                <option value="message">Message</option>
                <option value="thread_title">Thread title</option>
              </select>
            </label>
          </div>
        </fieldset>

        {errors.length > 0 && (
          <div className="form-error">
            <ul>
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="ask-form-actions">
          <button type="submit" disabled={saving}>
            {saving ? "Saving..." : "Save ask"}
          </button>
          <button type="button" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
