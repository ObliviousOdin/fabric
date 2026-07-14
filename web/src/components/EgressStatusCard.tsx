import { ShieldCheck } from "lucide-react";
import { Badge } from "@/components/fabric/Badge";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { H2 } from "@nous-research/ui/ui/components/typography/h2";

import type { StatusResponse } from "@/lib/api";

export function EgressStatusCard({
  egress,
}: {
  egress: NonNullable<StatusResponse["egress"]>;
}) {
  return (
    <section className="flex flex-col gap-3">
      <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
        <ShieldCheck className="h-4 w-4" /> Network &amp; AI egress
      </H2>
      <Card>
        <CardContent className="grid grid-cols-1 gap-3 py-4 text-sm sm:grid-cols-3">
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Mode</div>
            <div className="font-mono">{egress.mode}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Enforcement</div>
            <Badge tone={egress.available ? "success" : "destructive"}>
              {egress.status}
            </Badge>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">Scope</div>
            <div>{egress.scope.replaceAll("_", " ")}</div>
          </div>
          {egress.mode === "local_ai" && (
            <div>
              <div className="text-xs uppercase tracking-wider text-muted-foreground">Private networks</div>
              <div>{egress.allowed_private_cidr_count} explicitly approved</div>
            </div>
          )}
          {egress.reason && (
            <div className="sm:col-span-3 text-xs text-destructive">
              {egress.reason.replaceAll("_", " ")}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
