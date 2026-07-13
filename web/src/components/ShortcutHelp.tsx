import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@nous-research/ui/ui/components/dialog";
import {
  formatCombo,
  useShortcutRegistry,
} from "@/hooks/useShortcutRegistry";
import { useI18n } from "@/i18n";

interface ShortcutRow {
  combos: string[];
  description: string;
  key: number;
}

/**
 * Keyboard-shortcuts help dialog (opened with `?`). Lists whatever is
 * currently registered in the shortcut registry — live, not hardcoded —
 * grouped by each registration's scope label. Registrations sharing a
 * scope + description are alternate bindings for one command (e.g. the
 * "[" / mod+b sidebar pair), so they coalesce into a single row with one
 * kbd chip per combo.
 */
export function ShortcutHelp({ onClose, open }: ShortcutHelpProps) {
  const { t } = useI18n();
  const shortcuts = useShortcutRegistry();
  const title = t.commandPalette?.shortcutsTitle ?? "Keyboard shortcuts";
  const fallbackScope = t.commandPalette?.scopeGlobal ?? "Global";

  const groups: Array<{ scope: string; items: ShortcutRow[] }> = [];
  for (const shortcut of shortcuts) {
    const scope = shortcut.scope ?? fallbackScope;
    let group = groups.find((g) => g.scope === scope);
    if (!group) {
      group = { items: [], scope };
      groups.push(group);
    }
    const row = group.items.find(
      (r) => r.description === shortcut.description,
    );
    if (!row) {
      group.items.push({
        combos: [shortcut.combo],
        description: shortcut.description,
        key: shortcut.id,
      });
    } else if (!row.combos.includes(shortcut.combo)) {
      row.combos.push(shortcut.combo);
    }
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
                {group.items.map((row) => (
                  <li
                    className="flex items-center justify-between gap-4 px-2 py-1.5"
                    key={row.key}
                  >
                    <span className="min-w-0 flex-1 truncate font-sans text-sm text-text-secondary">
                      {row.description}
                    </span>
                    <span className="flex shrink-0 items-center gap-1">
                      {row.combos.map((combo) => (
                        <kbd
                          className="border border-border bg-secondary/40 px-1.5 py-0.5 font-mono-ui text-xs text-text-secondary"
                          key={combo}
                        >
                          {formatCombo(combo)}
                        </kbd>
                      ))}
                    </span>
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
