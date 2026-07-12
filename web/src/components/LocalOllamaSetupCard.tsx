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
export function LocalOllamaSetupCard({ onConfigured, refreshKey = 0 }: Props) {
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
        <CardContent className="grid gap-4">
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
                {discovering ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <RefreshCw />
                )}
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
        </CardContent>
      </Card>
      <Toast toast={toast} />
    </>
  );
}
