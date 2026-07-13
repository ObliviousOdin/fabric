import { useState } from "react";
import {
  Activity,
  Database,
  RotateCw,
  ShieldCheck,
  Stethoscope,
  Terminal,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { FabricConsoleModal } from "@/components/FabricConsoleModal";
import { api } from "@/lib/api";

export interface OperationsCardProps {
  /** Spawns the op and routes its log into the shared viewer (CN10/Y6). */
  onRunOp: (fn: () => Promise<{ name: string }>, label: string) => void;
}

/**
 * Operations card (Y6, frozen): console + the spawn-based ops. Doctor and
 * security audit stay text log tails — there is no structured check data
 * to render as a health board (§9.1/B25).
 */
export function OperationsCard({ onRunOp }: OperationsCardProps) {
  const [consoleOpen, setConsoleOpen] = useState(false);

  return (
    <>
      <FabricConsoleModal open={consoleOpen} onClose={() => setConsoleOpen(false)} />
      <Card>
        <CardContent className="flex flex-wrap gap-2 py-4">
          <Button
            size="sm"
            ghost
            prefix={<Terminal className="h-3.5 w-3.5" />}
            onClick={() => setConsoleOpen(true)}
          >
            Open console
          </Button>
          <Button
            size="sm"
            ghost
            prefix={<Stethoscope className="h-3.5 w-3.5" />}
            onClick={() => onRunOp(api.runDoctor, "Doctor")}
          >
            Run doctor
          </Button>
          <Button
            size="sm"
            ghost
            prefix={<ShieldCheck className="h-3.5 w-3.5" />}
            onClick={() => onRunOp(api.runSecurityAudit, "Security audit")}
          >
            Security audit
          </Button>
          <Button
            size="sm"
            ghost
            prefix={<RotateCw className="h-3.5 w-3.5" />}
            onClick={() => onRunOp(api.updateSkillsFromHub, "Skills update")}
          >
            Update skills
          </Button>
          <Button
            size="sm"
            ghost
            prefix={<Activity className="h-3.5 w-3.5" />}
            onClick={() => onRunOp(api.runPromptSize, "Prompt size")}
          >
            Prompt size
          </Button>
          <Button
            size="sm"
            ghost
            prefix={<Database className="h-3.5 w-3.5" />}
            onClick={() => onRunOp(api.runDump, "Support dump")}
          >
            Support dump
          </Button>
          <Button
            size="sm"
            ghost
            prefix={<RotateCw className="h-3.5 w-3.5" />}
            onClick={() => onRunOp(api.runConfigMigrate, "Config migrate")}
          >
            Migrate config
          </Button>
        </CardContent>
      </Card>
    </>
  );
}
