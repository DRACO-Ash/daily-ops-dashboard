import { useSearchParams } from "react-router-dom";
import AsksTab from "../components/mattermost/AsksTab";
import HistoryTab from "../components/mattermost/HistoryTab";
import MessagesTab from "../components/mattermost/MessagesTab";
import { useMattermostChannels } from "../components/mattermost/useMattermostChannels";
import { useAuth } from "../context/AuthContext";
import { canWrite } from "../utils/mattermostAsk";

type TabKey = "asks" | "history" | "messages";

const TABS: ReadonlyArray<{ key: TabKey; label: string }> = [
  { key: "asks", label: "Asks" },
  { key: "history", label: "Full history" },
  { key: "messages", label: "Messages" },
];

function parseTab(value: string | null): TabKey {
  const found = TABS.find((t) => t.key === value);
  return found ? found.key : "asks";
}

export default function MattermostPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseTab(searchParams.get("tab"));
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const channels = useMattermostChannels();

  return (
    <div>
      <h1>Comms</h1>
      <p className="muted-paragraph">
        Mattermost posts are pulled only by saved asks and by full history pulls you schedule.
      </p>
      {!writer && (
        <p className="muted">Read only: operators and admins can create, run and schedule pulls.</p>
      )}

      <nav className="tab-bar" aria-label="Comms views">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={t.key === tab ? "tab-button active" : "tab-button"}
            aria-current={t.key === tab ? "page" : undefined}
            onClick={() => setSearchParams(t.key === "asks" ? {} : { tab: t.key })}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "asks" && <AsksTab canWrite={writer} channels={channels} />}
      {tab === "history" && <HistoryTab canWrite={writer} channels={channels} />}
      {tab === "messages" && <MessagesTab />}
    </div>
  );
}
