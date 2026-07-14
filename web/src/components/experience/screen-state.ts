import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  CloudOff,
  FilterX,
  Inbox,
  LoaderCircle,
  LockKeyhole,
  OctagonAlert,
  RefreshCw,
  ShieldAlert,
  Trash2,
} from "lucide-react";

export type ScreenStateKind =
  | "normal"
  | "loading"
  | "empty"
  | "filtered-empty"
  | "degraded"
  | "offline"
  | "permission-denied"
  | "read-only"
  | "in-progress"
  | "success"
  | "failure"
  | "conflict"
  | "destructive-confirmation";

export interface StatePresentation {
  icon: LucideIcon;
  tone: string;
  role: "alert" | "status";
}

export const SCREEN_STATE_PRESENTATION: Record<
  Exclude<ScreenStateKind, "normal">,
  StatePresentation
> = {
  loading: {
    icon: LoaderCircle,
    tone: "text-muted-foreground",
    role: "status",
  },
  empty: { icon: Inbox, tone: "text-muted-foreground", role: "status" },
  "filtered-empty": {
    icon: FilterX,
    tone: "text-muted-foreground",
    role: "status",
  },
  degraded: {
    icon: AlertTriangle,
    tone: "text-warning",
    role: "alert",
  },
  offline: { icon: CloudOff, tone: "text-warning", role: "alert" },
  "permission-denied": {
    icon: ShieldAlert,
    tone: "text-destructive",
    role: "alert",
  },
  "read-only": { icon: LockKeyhole, tone: "text-warning", role: "status" },
  "in-progress": {
    icon: CircleDashed,
    tone: "text-primary",
    role: "status",
  },
  success: { icon: CheckCircle2, tone: "text-success", role: "status" },
  failure: { icon: OctagonAlert, tone: "text-destructive", role: "alert" },
  conflict: { icon: RefreshCw, tone: "text-warning", role: "alert" },
  "destructive-confirmation": {
    icon: Trash2,
    tone: "text-destructive",
    role: "alert",
  },
};

export const SCREEN_STATE_KINDS = [
  "normal",
  "loading",
  "empty",
  "filtered-empty",
  "degraded",
  "offline",
  "permission-denied",
  "read-only",
  "in-progress",
  "success",
  "failure",
  "conflict",
  "destructive-confirmation",
] as const satisfies readonly ScreenStateKind[];
