import { useCallback, useSyncExternalStore, type ComponentType } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import {
  getPluginComponent,
  getPluginLoadError,
  onPluginRegistered,
} from "./registry";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import type { Translations } from "@/i18n/types";
import type { DashboardPluginPageProps } from "./sdk";

/** Renders a plugin tab once its bundle has called `register()`. */
export function PluginPage({ name }: { name: string }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const navigatePlugin = useCallback(
    (
      to: string | number,
      options?: { replace?: boolean; state?: unknown },
    ) => {
      if (typeof to === "number") navigate(to);
      else navigate(to, { replace: options?.replace, state: options?.state });
    },
    [navigate],
  );
  // Subscribe in render (via useSyncExternalStore) so we never miss
  // `register()` if the script loads before a useEffect would run.
  const Component = useSyncExternalStore(
    (onChange) => onPluginRegistered(onChange),
    () => getPluginComponent(name) ?? null,
    () => null,
  );
  const loadError = useSyncExternalStore(
    (onChange) => onPluginRegistered(onChange),
    () => getPluginLoadError(name) ?? null,
    () => null,
  );

  if (Component) {
    // Retrieved from the registry (stable per plugin name), so the component
    // identity does not change across renders or remount spuriously.
    const RoutedComponent = Component as ComponentType<DashboardPluginPageProps>;
    return (
      <RoutedComponent
        navigate={navigatePlugin}
        location={{
          pathname: location.pathname,
          search: location.search,
          hash: location.hash,
        }}
      />
    );
  }

  if (loadError) {
    const message = formatPluginError(loadError, t);
    return (
      <div
        className={cn(
          "max-w-lg p-4",
          "font-sans text-sm tracking-normal text-text-secondary",
        )}
        role="alert"
      >
        {message}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 p-4",
        "font-sans text-sm tracking-normal text-text-tertiary",
      )}
    >
      <Spinner className="shrink-0" />
      <span>{t.common.loading}</span>
    </div>
  );
}

function formatPluginError(code: string, t: Translations): string {
  if (code === "LOAD_FAILED") return t.common.pluginLoadFailed;
  if (code === "NO_REGISTER") return t.common.pluginNotRegistered;
  return code;
}
