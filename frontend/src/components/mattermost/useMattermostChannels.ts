import { useCallback, useEffect, useState } from "react";
import { listMattermostChannels } from "../../api/mattermost";
import type { MattermostChannel } from "../../types";
import { apiErrorMessage } from "../../utils/mattermostAsk";

export interface ChannelsState {
  channels: MattermostChannel[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/** The bot's channels, fetched live from Mattermost through the API. */
export function useMattermostChannels(): ChannelsState {
  const [channels, setChannels] = useState<MattermostChannel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listMattermostChannels()
      .then((rows) => {
        if (!cancelled) setChannels(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(apiErrorMessage(err, "Failed to load Mattermost channels."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const reload = useCallback(() => setToken((t) => t + 1), []);
  return { channels, loading, error, reload };
}
