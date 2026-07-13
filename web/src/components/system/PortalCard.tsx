import { Badge } from "@nous-research/ui/ui/components/badge";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import type { PortalStatus } from "@/lib/api";

/** Nous Portal card (Y13): kept as-is — logged-in badge, provider line,
 *  Tool Gateway feature list, subscription link, `fabric portal` hint. */
export function PortalCard({ portal }: { portal: PortalStatus }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex items-center gap-3">
          <Badge tone={portal.logged_in ? "success" : "secondary"}>
            {portal.logged_in ? "logged in" : "not logged in"}
          </Badge>
          {portal.provider && (
            <span className="text-sm text-muted-foreground">
              inference provider: {portal.provider}
            </span>
          )}
          <a
            href={
              portal.subscription_url ||
              "https://portal.nousresearch.com/manage-subscription"
            }
            target="_blank"
            rel="noreferrer"
            className="ml-auto text-xs text-primary underline"
          >
            Manage subscription
          </a>
        </div>
        {portal.features && portal.features.length > 0 && (
          <div className="flex flex-col gap-1 border-t border-border pt-3">
            <span className="text-xs uppercase tracking-wider text-muted-foreground">
              Tool Gateway routing
            </span>
            {portal.features.map((f) => (
              <div
                key={f.label}
                className="flex items-center justify-between text-sm"
              >
                <span>{f.label}</span>
                <span className="text-muted-foreground">{f.state}</span>
              </div>
            ))}
          </div>
        )}
        {!portal.logged_in && (
          <p className="text-xs text-muted-foreground">
            Log in with <span className="font-mono">fabric portal</span>.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
