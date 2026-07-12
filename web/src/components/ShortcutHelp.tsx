import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@nous-research/ui/ui/components/dialog";
import {
  formatCombo,
  useShortcutRegistry,
  type RegisteredShortcut,
} from "@/hooks/useShortcutRegistry";
import { useI18n } from "@/i18n";

/**
 * Keyboard-shortcuts help dialog (opened with `?`). Lists whatever is
 * currently registered in the shortcut registry — live, not hardcoded —
 * grouped by each registration's scope label.
 */
export function ShortcutHelp({ onClose, open }: ShortcutHelpProps) {
  const { t } = useI18n();
  const shortcuts = useShortcutRegistry();
  const title = t.commandPalette?.shortcutsTitle ?? "Keyboard shortcuts";
  const fallbackScope = t.commandPalette?.scopeGlobal ?? "Global";

  const groups: Array<{ scope: string; items: RegisteredShortcut[] }> = [];
  for (const shortcut of shortcuts) {
    const scope = shortcut.scope ?? fallbackScope;
    const group = groups.find((g) => g.scope === scope);
    if (group) group.items.push(shortcut);
    else groups.push({ items: [shortcut], scope });
  }

  return (
    <Dialog onOpenChange={(o) => !o && onClose()} open={open}>
      <DialogContent aria-describedby={undefined} className="max-w-md gap-0 p-0">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className="max-h-[60dvh] overflow-y-auto px-2 py-2">
          {shortcuts.length === 0 && (
            <div className="px-2 py-6 text-center text-sm text-muted-foreground">
              {t.common.none}
            </div>
          )}

          {groups.map((group) => (
            <div key={group.scope}>
              <div className="px-2 pb-1 pt-2 font-sans text-display text-xs uppercase tracking-[0.12em] text-muted-foreground">
                {group.scope}
              </div>
              <ul className="flex flex-col">
                {group.items.map((shortcut) => (
                  <li
                    className="flex items-center justify-between gap-4 px-2 py-1.5"
                    key={shortcut.id}
                  >
                    <span className="min-w-0 flex-1 truncate font-sans text-sm text-text-secondary">
                      {shortcut.description}
                    </span>
                    <kbd className="shrink-0 border border-border bg-secondary/40 px-1.5 py-0.5 font-mono-ui text-xs text-text-secondary">
                      {formatCombo(shortcut.combo)}
                    </kbd>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface ShortcutHelpProps {
  onClose: () => void;
  open: boolean;
}
