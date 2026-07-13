import { Package } from "lucide-react";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import type { ProfileInfo } from "@/lib/api";
import { AgentStatusBadge, gatewayAgentStatus } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  ProfileActionsMenu,
  type ProfileActionsMenuProps,
} from "./ProfileActionsMenu";
import { PROFILE_NAME_RE } from "./profile-name";

export interface ProfileCardLabels {
  activeBadge: string;
  defaultBadge: string;
  aliasBadge: string;
  hasEnv: string;
  gatewayRunning: string;
  gatewayStopped: string;
  noDescription: string;
  reviewBadge: string;
  model: string;
  skills: string;
  invalidName: string;
  nameRule: string;
  save: string;
  cancel: string;
}

export interface ProfileCardProps {
  profile: ProfileInfo;
  active: boolean;
  labels: ProfileCardLabels;
  menuLabels: ProfileActionsMenuProps["labels"];
  settingActive: boolean;
  isEditingDesc: boolean;
  isEditingModel: boolean;
  isEditingSoul: boolean;
  /** Inline rename editor state (one rename at a time, owned by the page). */
  isRenaming: boolean;
  renameTo: string;
  onRenameToChange: (value: string) => void;
  onRenameSubmit: () => void;
  onRenameCancel: () => void;
  onCopyCommand: () => void;
  onDelete: () => void;
  onEditDescription: () => void;
  onEditModel: () => void;
  onEditSoul: () => void;
  onManageSkills: () => void;
  onRename: () => void;
  onSetActive: () => void;
}

/**
 * One agent identity (PR2). Page-local card grammar — the 3-col identity
 * grid is a different density class than `CapabilityRow` (the CAP3/R21
 * lesson: compose, don't force) — but the zones follow the shared order:
 * identity → runtime → description → evidence → actions.
 */
export function ProfileCard({
  profile: p,
  active,
  labels,
  menuLabels,
  settingActive,
  isEditingDesc,
  isEditingModel,
  isEditingSoul,
  isRenaming,
  renameTo,
  onRenameToChange,
  onRenameSubmit,
  onRenameCancel,
  onCopyCommand,
  onDelete,
  onEditDescription,
  onEditModel,
  onEditSoul,
  onManageSkills,
  onRename,
  onSetActive,
}: ProfileCardProps) {
  // Runtime axis (CN1): `gateway_running` is real per-profile process state
  // served by GET /api/profiles, so it wears the shared G1 vocabulary via
  // `gatewayAgentStatus` — live (pulse) when running, idle when stopped.
  const gateway = gatewayAgentStatus(null, p.gateway_running);

  if (isRenaming) {
    const trimmed = renameTo.trim();
    const invalid =
      trimmed !== "" && trimmed !== p.name && !PROFILE_NAME_RE.test(trimmed);
    return (
      <Card className="h-full">
        <CardContent className="flex h-full flex-col gap-2 py-4">
          <div className="flex flex-col gap-2">
            <Input
              autoFocus
              value={renameTo}
              onChange={(e) => onRenameToChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onRenameSubmit();
                if (e.key === "Escape") onRenameCancel();
              }}
              aria-invalid={invalid}
            />

            <p
              className={cn(
                "text-xs",
                invalid ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {invalid
                ? `${labels.invalidName}: ${labels.nameRule}`
                : labels.nameRule}
            </p>

            <div className="flex gap-1.5">
              <Button size="sm" onClick={onRenameSubmit}>
                {labels.save}
              </Button>

              <Button size="sm" ghost onClick={onRenameCancel}>
                {labels.cancel}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="h-full">
      <CardContent className="flex h-full flex-col gap-2 py-4">
        {/* Zone 1 — identity: name + configuration badges. Zone 5 (actions)
            keeps its top-right ⋯ affordance. */}
        <div className="flex items-start gap-2">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
            <span className="font-medium text-sm truncate">{p.name}</span>

            {active && <Badge tone="success">{labels.activeBadge}</Badge>}

            {p.is_default && (
              <Badge tone="secondary">{labels.defaultBadge}</Badge>
            )}

            {p.has_alias && <Badge tone="outline">{labels.aliasBadge}</Badge>}

            {p.has_env && <Badge tone="outline">{labels.hasEnv}</Badge>}

            {p.distribution_name && (
              <Badge tone="outline" className="gap-1">
                <Package className="h-3 w-3" />
                {p.distribution_name}
                {p.distribution_version ? `@${p.distribution_version}` : ""}
              </Badge>
            )}
          </div>

          <ProfileActionsMenu
            isActive={active}
            isDefault={p.is_default}
            isEditingDesc={isEditingDesc}
            isEditingModel={isEditingModel}
            isEditingSoul={isEditingSoul}
            settingActive={settingActive}
            labels={menuLabels}
            onCopyCommand={onCopyCommand}
            onDelete={onDelete}
            onEditDescription={onEditDescription}
            onEditModel={onEditModel}
            onEditSoul={onEditSoul}
            onManageSkills={onManageSkills}
            onRename={onRename}
            onSetActive={onSetActive}
          />
        </div>

        {/* Zone 2 — runtime: the per-profile gateway on the shared vocabulary. */}
        <div className="flex items-center gap-1.5 text-xs">
          <AgentStatusBadge
            status={gateway.status}
            label={p.gateway_running ? labels.gatewayRunning : labels.gatewayStopped}
          />
        </div>

        {/* Zone 3 — description ("what this agent is good at"). */}
        <div className="flex items-start gap-2 text-xs">
          <span
            className={cn(
              "line-clamp-2",
              p.description
                ? "text-muted-foreground"
                : "text-muted-foreground italic",
            )}
          >
            {p.description || labels.noDescription}
          </span>

          {p.description && p.description_auto && (
            <Badge tone="warning" className="shrink-0">
              {labels.reviewBadge}
            </Badge>
          )}
        </div>

        {/* Zone 4 — evidence (mono, muted): model · skills · path (G9). */}
        <div className="mt-auto flex flex-col gap-0.5 pt-1 font-mono text-xs text-muted-foreground">
          {p.model && (
            <span className="truncate">
              {labels.model}: {p.model}
              {p.provider ? ` (${p.provider})` : ""}
            </span>
          )}

          <span className="tabular-nums">
            {labels.skills}: {p.skill_count}
          </span>

          <span className="truncate" title={p.path}>
            {p.path}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
