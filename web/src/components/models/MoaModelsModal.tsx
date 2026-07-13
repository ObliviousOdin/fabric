import { useState } from "react";
import { api } from "@/lib/api";
import type { MoaConfigResponse, MoaModelSlot } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";

type MoaPickerTarget =
  | { kind: "reference"; index: number }
  | { kind: "aggregator" };

/**
 * Mixture-of-Agents preset editor (M2 MoA row). Internals frozen (N16):
 * preset CRUD, default-preset handling and the no-recursive-MoA guard —
 * moved verbatim out of the pre-split ModelsPage.
 */
export function MoaModelsModal({
  config,
  refreshKey,
  onClose,
  onSaved,
}: {
  config: MoaConfigResponse;
  refreshKey: number;
  onClose(): void;
  onSaved(next: MoaConfigResponse): void;
}) {
  const [draft, setDraft] = useState<MoaConfigResponse>(config);
  const [selected, setSelected] = useState(config.default_preset || Object.keys(config.presets)[0] || "default");
  const [newName, setNewName] = useState("");
  const [picker, setPicker] = useState<MoaPickerTarget | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const presetNames = Object.keys(draft.presets || {});
  const preset = draft.presets[selected] || draft.presets[presetNames[0]];
  const slotLabel = (slot: MoaModelSlot) => `${slot.provider || "(provider)"} · ${slot.model || "(model)"}`;

  const updateSelectedPreset = (updater: (preset: MoaConfigResponse["presets"][string]) => MoaConfigResponse["presets"][string]) => {
    setDraft((prev) => ({
      ...prev,
      presets: {
        ...prev.presets,
        [selected]: updater(prev.presets[selected]),
      },
    }));
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.saveMoaModels(draft);
      onSaved(saved);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const addPreset = () => {
    const name = newName.trim();
    if (!name || draft.presets[name]) return;
    const seed = preset || {
      reference_models: draft.reference_models,
      aggregator: draft.aggregator,
      reference_temperature: draft.reference_temperature,
      aggregator_temperature: draft.aggregator_temperature,
      max_tokens: draft.max_tokens,
      enabled: draft.enabled,
    };
    setDraft((prev) => ({
      ...prev,
      default_preset: prev.default_preset || name,
      presets: { ...prev.presets, [name]: { ...seed, reference_models: [...seed.reference_models] } },
    }));
    setSelected(name);
    setNewName("");
  };

  const deletePreset = () => {
    if (presetNames.length <= 1) return;
    const remaining = presetNames.filter((name) => name !== selected);
    const nextSelected = remaining[0];
    setDraft((prev) => {
      const next = { ...prev.presets };
      delete next[selected];
      return {
        ...prev,
        presets: next,
        default_preset: prev.default_preset === selected ? nextSelected : prev.default_preset,
        active_preset: prev.active_preset === selected ? "" : prev.active_preset,
      };
    });
    setSelected(nextSelected);
  };

  if (!preset) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4">
      <Card className="max-h-[85vh] w-full max-w-2xl overflow-auto">
        <CardHeader>
          <CardTitle className="text-sm">Configure Mixture of Agents presets</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-text-secondary">
            Presets appear as models under the Mixture of Agents provider. References produce perspectives; the aggregator is the acting model that answers and calls tools.
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <select
              className="border border-border bg-background px-2 py-1 text-xs"
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
            >
              {presetNames.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            <Button size="sm" outlined onClick={() => setDraft((prev) => ({ ...prev, default_preset: selected }))}>Set default</Button>
            <Button size="sm" ghost disabled={presetNames.length <= 1} onClick={deletePreset}>Delete</Button>
            <input
              className="border border-border bg-background px-2 py-1 text-xs"
              placeholder="new preset name"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
            />
            <Button size="sm" outlined disabled={!newName.trim() || !!draft.presets[newName.trim()]} onClick={addPreset}>Add preset</Button>
          </div>

          <div className="text-xs text-text-secondary">
            Default: <span className="font-mono">{draft.default_preset}</span>
          </div>

          <div className="space-y-2">
            <div className="text-display text-xs font-medium tracking-wider">Reference models</div>
            {preset.reference_models.map((slot, index) => (
              <div key={`${selected}-${slot.provider}-${slot.model}-${index}`} className="flex items-center gap-2 border border-border/50 bg-muted/20 px-3 py-2">
                <div className="min-w-0 flex-1 truncate font-mono text-xs text-text-secondary">{slotLabel(slot)}</div>
                <Button size="sm" outlined onClick={() => setPicker({ kind: "reference", index })}>Change</Button>
                <Button size="sm" ghost disabled={preset.reference_models.length <= 1} onClick={() => updateSelectedPreset((prev) => ({ ...prev, reference_models: prev.reference_models.filter((_, i) => i !== index) }))}>Remove</Button>
              </div>
            ))}
            <Button size="sm" outlined onClick={() => updateSelectedPreset((prev) => ({ ...prev, reference_models: [...prev.reference_models, prev.aggregator] }))}>Add reference model</Button>
          </div>

          <div className="space-y-2">
            <div className="text-display text-xs font-medium tracking-wider">Aggregator</div>
            <div className="flex items-center gap-2 border border-border/50 bg-muted/20 px-3 py-2">
              <div className="min-w-0 flex-1 truncate font-mono text-xs text-text-secondary">{slotLabel(preset.aggregator)}</div>
              <Button size="sm" outlined onClick={() => setPicker({ kind: "aggregator" })}>Change</Button>
            </div>
          </div>

          {error && <div className="text-xs text-destructive">{error}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <Button ghost onClick={onClose} disabled={busy}>Cancel</Button>
            <Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
          </div>
        </CardContent>
      </Card>
      {picker && (
        <ModelPickerDialog
          key={`moa-picker-${refreshKey}-${selected}-${picker.kind}-${picker.kind === "reference" ? picker.index : "agg"}`}
          loader={api.getModelOptions}
          alwaysGlobal
          title="Select MoA Model"
          onApply={async ({ provider, model }) => {
            if ((provider || "").toLowerCase() === "moa") {
              setError("MoA presets can't reference or aggregate the Mixture of Agents provider (no recursive MoA).");
              return;
            }
            setError(null);
            updateSelectedPreset((prev) => {
              if (picker.kind === "aggregator") return { ...prev, aggregator: { provider, model } };
              return {
                ...prev,
                reference_models: prev.reference_models.map((slot, i) => i === picker.index ? { provider, model } : slot),
              };
            });
          }}
          onClose={() => setPicker(null)}
        />
      )}
    </div>
  );
}
