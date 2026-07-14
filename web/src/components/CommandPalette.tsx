import {
  useEffect,
  useId,
  useMemo,
  useState,
  type ComponentType,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  Check,
  Keyboard,
  MessageSquarePlus,
  Palette,
  PanelLeftClose,
  RotateCw,
  Search,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@nous-research/ui/ui/components/dialog";
import { Input } from "@nous-research/ui/ui/components/input";
import { ListItem } from "@nous-research/ui/ui/components/list-item";
import { RestartGatewayConfirm } from "@/components/RestartGatewayConfirm";
import { navItemLabel } from "@/components/sidebar/nav-label";
import type { NavItem, NavSection } from "@/components/sidebar/nav-model";
import { useSystemActions } from "@/contexts/useSystemActions";
import { formatCombo } from "@/hooks/useShortcutRegistry";
import { useI18n } from "@/i18n";
import type { Translations } from "@/i18n/types";
import { fuzzyRank } from "@/lib/fuzzy";
import { cn } from "@/lib/utils";
import { useTheme } from "@/themes";

type PaletteGroup = "pages" | "actions" | "themes";

const GROUP_ORDER: PaletteGroup[] = ["pages", "actions", "themes"];

interface PaletteCommand {
  /** Marks the currently active option (e.g. the applied theme). */
  active?: boolean;
  group: PaletteGroup;
  /** Right-aligned technical hint (path, shortcut) — rendered in mono. */
  hint?: string;
  icon: ComponentType<{ className?: string }>;
  id: string;
  label: string;
  perform: () => void;
  /** Fuzzy-match haystack; defaults to the label alone. */
  searchText: string;
}

/**
 * Global ⌘K command palette. Sources its Pages group from the same nav
 * structures the sidebar renders (built-ins + plugin tabs), so the two can
 * never drift; Actions cover new chat / restart gateway / toggle sidebar /
 * shortcuts help; Themes list the presets from the theme context.
 *
 * Combobox pattern: focus stays in the input, options are traversed via
 * `aria-activedescendant`. Focus returns to the invoking element on close
 * (Radix Dialog restores it).
 */
export function CommandPalette({
  embeddedChat,
  onClose,
  onShowShortcuts,
  open,
  pluginItems,
  sections,
  toggleCollapsed,
}: CommandPaletteProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { isBusy } = useSystemActions();
  const { availableThemes, setTheme, themeName } = useTheme();
  const [restartConfirmOpen, setRestartConfirmOpen] = useState(false);

  const commands = useMemo<PaletteCommand[]>(() => {
    const list: PaletteCommand[] = [];

    // ── Pages — flatten the sidebar sections + plugin group ──
    const navItems = [...sections.flatMap((s) => s.items), ...pluginItems];
    const seen = new Set<string>();
    for (const item of navItems) {
      if (seen.has(item.path)) continue;
      seen.add(item.path);
      const label = navItemLabel(item, t);
      list.push({
        group: "pages",
        hint: item.path,
        icon: item.icon,
        id: `page:${item.path}`,
        label,
        perform: () => {
          navigate(item.path);
          onClose();
        },
        searchText: `${label} ${item.path}`,
      });
    }

    // ── Actions ──
    if (embeddedChat) {
      list.push({
        group: "actions",
        icon: MessageSquarePlus,
        id: "action:new-chat",
        label: t.sessions.newChat,
        perform: () => {
          // A bare canonical Chat route clears any ?resume= target, spawning a fresh
          // session (same fallback ChatSessionList uses).
          navigate("/workspace/chat");
          onClose();
        },
        searchText: `${t.sessions.newChat} chat session`,
      });
    }
    if (!isBusy) {
      list.push({
        group: "actions",
        icon: RotateCw,
        id: "action:restart-gateway",
        label: t.status.restartGateway,
        perform: () => {
          onClose();
          setRestartConfirmOpen(true);
        },
        searchText: `${t.status.restartGateway} gateway restart`,
      });
    }
    list.push({
      group: "actions",
      // Advertise the layout-safe binding — "[" needs AltGr on many
      // European layouts (see the mod+b registration in App.tsx).
      hint: formatCombo("mod+b"),
      icon: PanelLeftClose,
      id: "action:toggle-sidebar",
      label: t.commandPalette?.toggleSidebar ?? "Toggle sidebar",
      perform: () => {
        toggleCollapsed();
        onClose();
      },
      searchText: `${t.commandPalette?.toggleSidebar ?? "Toggle sidebar"} sidebar collapse`,
    });
    list.push({
      group: "actions",
      hint: formatCombo("?"),
      icon: Keyboard,
      id: "action:show-shortcuts",
      label: t.commandPalette?.shortcutsTitle ?? "Keyboard shortcuts",
      perform: () => {
        onShowShortcuts();
      },
      searchText: `${t.commandPalette?.shortcutsTitle ?? "Keyboard shortcuts"} help keys`,
    });

    // ── Themes — presets from the theme context (may still be loading;
    // built-ins are always present so the group never breaks) ──
    for (const theme of availableThemes) {
      list.push({
        active: theme.name === themeName,
        group: "themes",
        hint: theme.name,
        icon: Palette,
        id: `theme:${theme.name}`,
        label: theme.label,
        perform: () => {
          setTheme(theme.name);
          onClose();
        },
        searchText: `${theme.label} ${theme.name} theme`,
      });
    }

    return list;
  }, [
    availableThemes,
    embeddedChat,
    isBusy,
    navigate,
    onClose,
    onShowShortcuts,
    pluginItems,
    sections,
    setTheme,
    t,
    themeName,
    toggleCollapsed,
  ]);

  const title = t.commandPalette?.title ?? "Command palette";

  return (
    <>
      <Dialog onOpenChange={(o) => !o && onClose()} open={open}>
        <DialogContent
          aria-describedby={undefined}
          className="top-[16%] max-w-xl translate-y-0 gap-0 overflow-hidden p-0"
          showCloseButton={false}
        >
          <DialogTitle className="sr-only">{title}</DialogTitle>
          {/* Remount the body per open so query/selection reset via state
              initializers (canonical dialog-body pattern). */}
          {open && <PaletteBody commands={commands} t={t} title={title} />}
        </DialogContent>
      </Dialog>

      <RestartGatewayConfirm
        onClose={() => setRestartConfirmOpen(false)}
        open={restartConfirmOpen}
      />
    </>
  );
}

function groupLabel(group: PaletteGroup, t: Translations): string {
  switch (group) {
    case "pages":
      return t.commandPalette?.pages ?? "Pages";
    case "actions":
      return t.commandPalette?.actions ?? "Actions";
    case "themes":
      return t.commandPalette?.themes ?? "Themes";
  }
}

function PaletteBody({
  commands,
  t,
  title,
}: {
  commands: PaletteCommand[];
  t: Translations;
  title: string;
}) {
  const listboxId = useId();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const groups = useMemo(() => {
    const ranked = fuzzyRank(commands, query, (c) => c.searchText);
    const byGroup = new Map<PaletteGroup, PaletteCommand[]>();
    for (const { item } of ranked) {
      const bucket = byGroup.get(item.group);
      if (bucket) bucket.push(item);
      else byGroup.set(item.group, [item]);
    }
    return GROUP_ORDER.filter((g) => byGroup.has(g)).map((g) => ({
      commands: byGroup.get(g)!,
      id: g,
    }));
  }, [commands, query]);

  const flat = useMemo(() => groups.flatMap((g) => g.commands), [groups]);
  const indexOf = useMemo(() => {
    const map = new Map<string, number>();
    flat.forEach((c, i) => map.set(c.id, i));
    return map;
  }, [flat]);

  const effectiveIndex =
    flat.length === 0 ? -1 : Math.min(activeIndex, flat.length - 1);
  const activeCommand = effectiveIndex >= 0 ? flat[effectiveIndex] : null;
  const optionDomId = (command: PaletteCommand) =>
    `${listboxId}-${command.id}`;
  const activeOptionId = activeCommand ? optionDomId(activeCommand) : undefined;

  useEffect(() => {
    if (!activeOptionId) return;
    document.getElementById(activeOptionId)?.scrollIntoView?.({
      block: "nearest",
    });
  }, [activeOptionId]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (flat.length) setActiveIndex((effectiveIndex + 1) % flat.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (flat.length) {
        setActiveIndex((effectiveIndex - 1 + flat.length) % flat.length);
      }
    } else if (event.key === "Home" && flat.length) {
      event.preventDefault();
      setActiveIndex(0);
    } else if (event.key === "End" && flat.length) {
      event.preventDefault();
      setActiveIndex(flat.length - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      activeCommand?.perform();
    }
  };

  return (
    <div onKeyDown={onKeyDown}>
      <div className="flex items-center gap-2 border-b border-border px-3">
        <Search aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <Input
          aria-activedescendant={activeOptionId}
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded
          aria-label={title}
          autoFocus
          className="h-11 border-0 bg-transparent px-0 font-sans text-sm focus-visible:border-0 focus-visible:ring-0"
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveIndex(0);
          }}
          placeholder={t.commandPalette?.placeholder ?? "Type a command or search…"}
          role="combobox"
          value={query}
        />
      </div>

      <div
        className="max-h-[min(60dvh,22rem)] overflow-y-auto py-1"
        id={listboxId}
        role="listbox"
        aria-label={title}
      >
        {flat.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            {t.commandPalette?.noResults ?? t.common.noResults}
          </div>
        )}

        {groups.map((group) => {
          const headerId = `${listboxId}-group-${group.id}`;
          return (
            <div aria-labelledby={headerId} key={group.id} role="group">
              <div
                className="px-3 pb-1 pt-2.5 font-sans text-display text-xs uppercase tracking-[0.12em] text-muted-foreground"
                id={headerId}
              >
                {groupLabel(group.id, t)}
              </div>

              {group.commands.map((command) => {
                const index = indexOf.get(command.id) ?? -1;
                const isActive = index === effectiveIndex;
                const Icon = command.icon;
                return (
                  <ListItem
                    active={isActive}
                    // Theme options carry the applied state; pages/actions
                    // leave it undefined so the attribute is omitted.
                    aria-checked={command.active}
                    aria-selected={isActive}
                    className="gap-3 px-3 py-1.5 font-sans text-sm normal-case tracking-normal"
                    id={optionDomId(command)}
                    key={command.id}
                    onClick={() => command.perform()}
                    onMouseMove={() => {
                      if (!isActive) setActiveIndex(index);
                    }}
                    role="option"
                    tabIndex={-1}
                  >
                    <Icon aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate">{command.label}</span>
                    {command.active && (
                      <Check aria-hidden className="h-3 w-3 shrink-0 text-primary" />
                    )}
                    {command.hint && (
                      <span className="shrink-0 font-mono-ui text-xs text-muted-foreground">
                        {command.hint}
                      </span>
                    )}
                  </ListItem>
                );
              })}
            </div>
          );
        })}
      </div>

      <div
        aria-hidden
        className={cn(
          "flex items-center gap-4 border-t border-border px-3 py-2",
          "text-xs text-muted-foreground",
        )}
      >
        <span className="inline-flex items-center gap-1">
          <PaletteKbd>↑↓</PaletteKbd>
          {t.commandPalette?.hintNavigate ?? "navigate"}
        </span>
        <span className="inline-flex items-center gap-1">
          <PaletteKbd>↵</PaletteKbd>
          {t.commandPalette?.hintSelect ?? "select"}
        </span>
        <span className="inline-flex items-center gap-1">
          <PaletteKbd>esc</PaletteKbd>
          {t.commandPalette?.hintClose ?? "close"}
        </span>
      </div>
    </div>
  );
}

// Chip classes kept byte-identical with the <kbd> in ShortcutHelp.tsx so the
// two keyboard surfaces render the same semantic element at the same size.
function PaletteKbd({ children }: { children: string }) {
  return (
    <kbd className="border border-border bg-secondary/40 px-1.5 py-0.5 font-mono-ui text-xs text-text-secondary">
      {children}
    </kbd>
  );
}

export interface CommandPaletteProps {
  embeddedChat: boolean;
  onClose: () => void;
  /** Close the palette and open the shortcuts-help dialog. */
  onShowShortcuts: () => void;
  open: boolean;
  pluginItems: NavItem[];
  sections: NavSection[];
  toggleCollapsed: () => void;
}
