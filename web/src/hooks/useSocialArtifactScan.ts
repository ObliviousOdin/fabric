import { useCallback, useEffect, useState } from "react";

import { extractSocialArtifacts, type SocialArtifact } from "@fabric/shared";

import { api, type SessionInfo } from "@/lib/api";

const INITIAL_SCAN = 25;
const SCAN_STEP = 25;
const SCAN_CONCURRENCY = 4;
// Cap how many messages we pull per session while looking for the post.
const MESSAGE_SCAN_LIMIT = 250;

export interface SocialSessionArtifacts {
  session: SessionInfo;
  artifacts: SocialArtifact[];
}

/** Run an async mapper over items with a fixed concurrency ceiling. */
async function mapLimit<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let cursor = 0;
  const worker = async () => {
    let index = cursor;
    cursor += 1;
    while (index < items.length) {
      results[index] = await fn(items[index], index);
      index = cursor;
      cursor += 1;
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, worker),
  );
  return results;
}

export interface SocialArtifactScan {
  error: string | null;
  loading: boolean;
  /** Re-run the scan at the current depth. */
  rescan: () => void;
  results: SocialSessionArtifacts[];
  /** Deepen the scan by another page of sessions. */
  scanMore: () => void;
  /** How many conversations the last scan covered. */
  scanned: number;
  /** True once at least one scan has finished (successfully or not). */
  settled: boolean;
}

/**
 * Scan recent conversations for Social Studio artifacts. Owned by the Social
 * page (not the Library) so the page can gate its stages on whether any post
 * actually exists, and the Library renders whatever the shared scan found.
 */
export function useSocialArtifactScan(): SocialArtifactScan {
  const [results, setResults] = useState<SocialSessionArtifacts[]>([]);
  const [scanCount, setScanCount] = useState(INITIAL_SCAN);
  const [scanned, setScanned] = useState(0);
  const [loading, setLoading] = useState(true);
  const [settled, setSettled] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scan = useCallback(async (count: number) => {
    setLoading(true);
    setError(null);
    try {
      const { sessions } = await api.getSessions(count, 0, undefined, "recent");
      const candidates = sessions.filter(
        (session) => session.message_count > 0,
      );
      const scannedResults = await mapLimit(
        candidates,
        SCAN_CONCURRENCY,
        async (session): Promise<SocialSessionArtifacts | null> => {
          try {
            const resp = await api.getSessionMessages(session.id, undefined, {
              limit: MESSAGE_SCAN_LIMIT,
            });
            const artifacts = extractSocialArtifacts(resp.messages);
            return artifacts.length ? { session, artifacts } : null;
          } catch {
            return null;
          }
        },
      );
      setResults(
        scannedResults.filter(
          (row): row is SocialSessionArtifacts => row !== null,
        ),
      );
      setScanned(candidates.length);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
      setSettled(true);
    }
  }, []);

  useEffect(() => {
    void scan(scanCount);
  }, [scan, scanCount]);

  const rescan = useCallback(() => {
    void scan(scanCount);
  }, [scan, scanCount]);

  const scanMore = useCallback(() => {
    setScanCount((count) => count + SCAN_STEP);
  }, []);

  return { error, loading, rescan, results, scanMore, scanned, settled };
}
