import { useCallback, useEffect, useState } from "react";
import { Check, Cpu, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { LocalModelProvider } from "@/lib/api";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Toast } from "@nous-research/ui/ui/components/toast";

interface Props {
  onConfigured?: () => void;
  refreshKey?: number;
  /**
   * Render as a row group inside the Models loadout card (spec M2) instead
   * of a standalone Card. Behavior — passive catalog load, explicit-button
   * discovery, configure flow — is identical in both variants (N14).
   */
  embedded?: boolean;
}

const stateMessage = (state: string): string => {
  if (state === "auth_failed") {
    return "This endpoint requires authentication. Use the advanced Custom endpoint flow.";
  }
  if (state === "protocol_mismatch") {
    return "The server did not satisfy Ollama's native catalog protocol.";
  }
  return "Ollama could not be reached. Start it and check the server URL.";
};

/** First-class, keyless native Ollama setup for the web Models page. */
export function LocalOllamaSetupCard({
  onConfigured,
  refreshKey = 0,
  embedded = false,
}: Props) {
  const { toast, showToast } = useToast();
  const [provider, setProvider] = useState<LocalModelProvider | null>(null);
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:11434");
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [configuring, setConfiguring] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    return api
      .getLocalModelProviders()
      .then((result) => {
        const row =
          result.providers.find((item) => item.id === "ollama") ?? null;
        setProvider(row);
        if (row) {
          setBaseUrl(row.base_url || row.default_base_url);
          setModels(row.model ? [row.model] : []);
          setSelectedModel(row.model || "");
        }
      })
      .catch((error) => {
        showToast(
          error instanceof Error
            ? error.message
            : "Could not load local providers",
          "error",
        );
      })
      .finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const discover = async () => {
    setDiscovering(true);
    setMessage("");
    try {
      const result = await api.discoverLocalOllama(baseUrl);
      setBaseUrl(result.base_url);
      setModels(result.models);
      setSelectedModel((previous) =>
        result.models.includes(previous) ? previous : (result.models[0] ?? ""),
      );
      setMessage(
        result.state === "reachable"
          ? result.models.length
            ? `${result.models.length} installed model${result.models.length === 1 ? "" : "s"} found.`
            : "Ollama is reachable but has no installed models."
          : stateMessage(result.state),
      );
    } catch (error) {
      setModels([]);
      setSelectedModel("");
      showToast(
        error instanceof Error
          ? error.message
          : "Could not discover Ollama models",
        "error",
      );
    } finally {
      setDiscovering(false);
    }
  };

  const configure = async () => {
    if (!selectedModel) return;
    setConfiguring(true);
    try {
      const result = await api.configureLocalOllama(baseUrl, selectedModel);
      setBaseUrl(result.base_url);
      setProvider((current) =>
        current
          ? {
              ...current,
              base_url: result.base_url,
              configured: true,
              model: result.model,
            }
          : current,
      );
      setMessage(`${result.model} now runs through native Ollama.`);
      showToast("Local Ollama model configured", "success");
      onConfigured?.();
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "Could not configure Ollama",
        "error",
      );
    } finally {
      setConfiguring(false);
    }
  };

  if (loading || !provider) return null;

  const body = (
    <>
      <div className="grid gap-1.5">
        <Label htmlFor="local-ollama-url">Ollama server URL</Label>
        <div className="flex flex-wrap gap-2">
          <Input
            id="local-ollama-url"
            className="min-w-64 flex-1 font-mono"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
          />
          <Button
            type="button"
            outlined
            disabled={discovering || configuring || !baseUrl.trim()}
            onClick={() => void discover()}
          >
            {discovering ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {discovering ? "Discovering…" : "Refresh"}
          </Button>
        </div>
      </div>

      {models.length > 0 ? (
        <div className="grid gap-1.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <div className="grid gap-1.5">
            <Label htmlFor="local-ollama-model">Installed model</Label>
            <Select
              id="local-ollama-model"
              value={selectedModel}
              onValueChange={setSelectedModel}
            >
              {models.map((model) => (
                <SelectOption key={model} value={model}>
                  {model}
                </SelectOption>
              ))}
            </Select>
          </div>
          <Button
            type="button"
            disabled={!selectedModel || configuring}
            onClick={() => void configure()}
          >
            {configuring && <Loader2 className="animate-spin" />}
            {configuring ? "Applying…" : "Use model"}
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {message || "Start Ollama, then refresh. To install a model, run"}{" "}
          <code className="font-mono">{provider.pull_command}</code>
        </p>
      )}

      {message && models.length > 0 && (
        <p className="text-sm text-muted-foreground">{message}</p>
      )}
    </>
  );

  if (embedded) {
    // Loadout row-group variant (M2): same content and behavior, styled as
    // the fourth row inside the Models page's assignment surface. When the
    // provider is configured it shows the CAP2 success-tone `active` badge
    // (the `title` carries the R16 "new sessions" truthfulness copy).
    return (
      <>
        <div className="flex min-w-0 flex-col gap-3 bg-muted/20 border border-border/50 px-3 py-2">
          <div className="min-w-0">
            <div className="mb-0.5 flex flex-wrap items-center gap-2">
              <Cpu className="h-3 w-3 text-text-tertiary" />
              <span className="text-display text-xs font-medium tracking-wider">
                {provider.name}
              </span>
              {provider.configured && (
                <Badge
                  tone="success"
                  className="text-xs"
                  title="applies to new sessions"
                >
                  active
                </Badge>
              )}
            </div>
            <p className="text-xs text-text-secondary">
              {provider.description}. Discovery runs only when you press
              Refresh.
            </p>
          </div>
          <div className="grid gap-3">{body}</div>
        </div>
        <Toast toast={toast} />
      </>
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Cpu className="size-4" />
                {provider.name}
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                {provider.description}. Discovery runs only when you press
                Refresh.
              </p>
            </div>
            {provider.configured && (
              <Badge tone="secondary" className="gap-1">
                <Check className="size-3" /> Connected
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="grid gap-4">{body}</CardContent>
      </Card>
      <Toast toast={toast} />
    </>
  );
}
