import { useEffect, useRef, useState } from "react";
import {
  AlignLeft,
  Check,
  ChevronDown,
  Cpu,
  MoreVertical,
  Package,
  Pencil,
  Terminal,
  Trash2,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { cn } from "@/lib/utils";

export interface ProfileActionsMenuProps {
  isActive: boolean;
  isDefault: boolean;
  isEditingDesc: boolean;
  isEditingModel: boolean;
  isEditingSoul: boolean;
  labels: {
    actions: string;
    delete: string;
    editDescription: string;
    editModel: string;
    editSoul: string;
    manageSkills: string;
    openInTerminal: string;
    rename: string;
    setActive: string;
  };
  settingActive: boolean;
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
 * Per-card "⋯" actions menu. Holds every action for the profile (set active,
 * model, description, SOUL, copy command, rename, delete) so the card row stays
 * a single button. Mirrors the hand-rolled dropdown pattern used by ModelsPage's
 * "Use as" menu (button + absolute panel + outside-click close).
 *
 * PR2.5: menu contents are frozen — set active hidden when active, rename +
 * delete hidden for the default profile. The `open-terminal` server endpoint
 * stays unbound (§6.1 decision): "copy the setup command" covers the intent.
 */
export function ProfileActionsMenu({
  isActive,
  isDefault,
  isEditingDesc,
  isEditingModel,
  isEditingSoul,
  labels,
  settingActive,
  onCopyCommand,
  onDelete,
  onEditDescription,
  onEditModel,
  onEditSoul,
  onManageSkills,
  onRename,
  onSetActive,
}: ProfileActionsMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node | null;
      // Close only when the click lands outside *this* menu. Matching any
      // `[data-profile-actions]` would treat another card's menu as "inside"
      // and leave several menus open at once.
      if (target && !containerRef.current?.contains(target)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  // Run the action, then collapse the menu. Toggle editors (model/description/
  // SOUL) expand the inline section below the card once the menu closes.
  const run = (fn: () => void) => () => {
    fn();
    setOpen(false);
  };

  const itemClass =
    "flex w-full items-center gap-2.5 px-3 py-2 text-xs uppercase tracking-wider hover:bg-muted/50 disabled:opacity-40";

  return (
    <div className="relative" data-profile-actions ref={containerRef}>
      <Button
        ghost
        size="icon"
        title={labels.actions}
        aria-label={labels.actions}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <MoreVertical className="h-4 w-4" />
      </Button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 min-w-[200px] border border-border bg-card shadow-lg"
        >
          {!isActive && (
            <button
              type="button"
              role="menuitem"
              className={itemClass}
              disabled={settingActive}
              onClick={run(onSetActive)}
            >
              <Check className="h-4 w-4" />
              {labels.setActive}
            </button>
          )}

          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={run(onEditModel)}
          >
            {isEditingModel ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <Cpu className="h-4 w-4" />
            )}
            {labels.editModel}
          </button>

          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={run(onEditDescription)}
          >
            {isEditingDesc ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <AlignLeft className="h-4 w-4" />
            )}
            {labels.editDescription}
          </button>

          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={run(onEditSoul)}
          >
            {isEditingSoul ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <span aria-hidden className="w-4 text-center text-xs font-bold">
                S
              </span>
            )}
            {labels.editSoul}
          </button>

          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={run(onManageSkills)}
          >
            <Package className="h-4 w-4" />
            {labels.manageSkills}
          </button>

          <button
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={run(onCopyCommand)}
          >
            <Terminal className="h-4 w-4" />
            {labels.openInTerminal}
          </button>

          {!isDefault && (
            <button
              type="button"
              role="menuitem"
              className={cn(itemClass, "border-t border-border/50")}
              onClick={run(onRename)}
            >
              <Pencil className="h-4 w-4" />
              {labels.rename}
            </button>
          )}

          {!isDefault && (
            <button
              type="button"
              role="menuitem"
              className={cn(itemClass, "text-destructive hover:bg-destructive/10")}
              onClick={run(onDelete)}
            >
              <Trash2 className="h-4 w-4" />
              {labels.delete}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
