import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import { Database, Download, Upload } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { ConfirmDialog } from "@nous-research/ui/ui/components/confirm-dialog";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { api } from "@/lib/api";
import type { ShowToast } from "./format";

type BackupImportTarget =
  | { kind: "upload"; file: File }
  | { kind: "path"; path: string };

function backupImportLabel(target: BackupImportTarget | null): string {
  if (!target) return "the archive";
  return target.kind === "upload" ? target.file.name : target.path;
}

function backupFileName(path: string | null): string {
  if (!path) return "No backup created yet";
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

/** Spawn-action completion callback shape (page ActionLogViewer `onComplete`). */
export type ActionCompleteHandler = (
  action: string,
  exitCode: number | null,
) => void;

export interface BackupRestoreCardProps {
  setActiveAction: (name: string) => void;
  showToast: ShowToast;
  /**
   * Registration slot for the page's ActionLogViewer `onComplete`: the
   * card installs its handler here so the "backup" completion (pending
   * archive → downloadable only on exit 0) keeps living next to the
   * backup state it mutates.
   */
  completionHandlerRef: MutableRefObject<ActionCompleteHandler | null>;
}

/**
 * Backup/restore card (Y7, frozen flows): create backup (archive becomes
 * downloadable only on `exit_code === 0`), blob download, and both restore
 * paths behind the destructive force-confirm dialog.
 */
export function BackupRestoreCard({
  setActiveAction,
  showToast,
  completionHandlerRef,
}: BackupRestoreCardProps) {
  const [pendingBackupArchive, setPendingBackupArchive] = useState<string | null>(
    null,
  );
  const [downloadableBackupArchive, setDownloadableBackupArchive] = useState<
    string | null
  >(null);
  const [downloadingBackup, setDownloadingBackup] = useState(false);
  const importUploadInputRef = useRef<HTMLInputElement | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPath, setImportPath] = useState("");
  // Restore-from-backup is destructive (overwrites the live config) and the
  // spawned `fabric import` runs non-interactively (stdin is /dev/null), so
  // its CLI "Continue? [y/N]" prompt would auto-abort. The dashboard owns the
  // consent: confirm here, then call the endpoint with force=true.
  const [importingBackup, setImportingBackup] = useState(false);
  const [importConfirmTarget, setImportConfirmTarget] =
    useState<BackupImportTarget | null>(null);

  // Backup completion: pending archive → downloadable only on exit 0 (Y7).
  const handleActionComplete = useCallback<ActionCompleteHandler>(
    (action, exitCode) => {
      if (action !== "backup" || !pendingBackupArchive) return;
      if (exitCode === 0) {
        setDownloadableBackupArchive(pendingBackupArchive);
        showToast("Backup ready to download", "success");
      } else {
        setPendingBackupArchive(null);
      }
    },
    [pendingBackupArchive, showToast],
  );
  useEffect(() => {
    completionHandlerRef.current = handleActionComplete;
    return () => {
      completionHandlerRef.current = null;
    };
  }, [completionHandlerRef, handleActionComplete]);

  const runDashboardBackup = async () => {
    try {
      const res = await api.runBackup();
      setActiveAction(res.name);
      setPendingBackupArchive(res.archive ?? null);
      setDownloadableBackupArchive(null);
      showToast("Backup started", "success");
    } catch (e) {
      showToast(`Backup failed: ${e}`, "error");
    }
  };

  const downloadBackup = async () => {
    const archive = downloadableBackupArchive;
    if (!archive) return;
    setDownloadingBackup(true);
    try {
      const res = await api.downloadBackup(archive);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = backupFileName(archive);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      showToast(`Download failed: ${e}`, "error");
    } finally {
      setDownloadingBackup(false);
    }
  };

  const clearImportFile = () => {
    setImportFile(null);
    if (importUploadInputRef.current) importUploadInputRef.current.value = "";
  };

  const runBackupImport = async (target: BackupImportTarget) => {
    setImportingBackup(true);
    try {
      const res =
        target.kind === "upload"
          ? await api.runImportUpload(target.file, true)
          : await api.runImport(target.path, true);
      setActiveAction(res.name);
      showToast("Import started", "success");
      if (target.kind === "upload") clearImportFile();
    } catch (e) {
      showToast(`Import failed: ${e}`, "error");
    } finally {
      setImportingBackup(false);
    }
  };

  return (
    <Card>
      <input
        ref={importUploadInputRef}
        type="file"
        accept=".zip,application/zip,application/x-zip-compressed"
        className="hidden"
        onChange={(event) => {
          setImportFile(event.currentTarget.files?.[0] ?? null);
        }}
      />
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <div className="grid min-w-0 flex-1 gap-2">
            <Label>Full backup</Label>
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
              <Button
                size="sm"
                ghost
                prefix={<Database className="h-3.5 w-3.5" />}
                onClick={() => void runDashboardBackup()}
              >
                Create backup
              </Button>
              <Button
                size="sm"
                ghost
                disabled={!downloadableBackupArchive || downloadingBackup}
                prefix={
                  downloadingBackup ? (
                    <Spinner className="h-3.5 w-3.5" />
                  ) : (
                    <Download className="h-3.5 w-3.5" />
                  )
                }
                onClick={() => void downloadBackup()}
              >
                Download backup
              </Button>
              <span
                className="min-w-0 truncate text-xs text-muted-foreground"
                title={pendingBackupArchive ?? "No backup created yet"}
              >
                {backupFileName(pendingBackupArchive)}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-end">
          <div className="grid min-w-0 flex-1 gap-2">
            <Label>Restore from backup upload</Label>
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
              <Button
                type="button"
                size="sm"
                ghost
                disabled={importingBackup}
                prefix={<Upload className="h-3.5 w-3.5" />}
                onClick={() => importUploadInputRef.current?.click()}
              >
                Choose restore zip
              </Button>
              <span
                className="min-w-0 truncate text-xs text-muted-foreground"
                title={importFile?.name ?? "No backup archive selected"}
              >
                {importFile?.name ?? "No backup archive selected"}
              </span>
            </div>
          </div>
          <Button
            size="sm"
            ghost
            disabled={!importFile || importingBackup}
            prefix={importingBackup ? <Spinner /> : undefined}
            onClick={() => {
              if (!importFile) return;
              setImportConfirmTarget({ kind: "upload", file: importFile });
            }}
          >
            Restore upload
          </Button>
        </div>

        <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-end">
          <div className="grid min-w-0 flex-1 gap-2">
            <Label htmlFor="import-path">Restore from backups path</Label>
            <Input
              id="import-path"
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
              placeholder="$FABRIC_HOME/backups/fabric-backup.zip"
            />
          </div>
          <Button
            size="sm"
            ghost
            disabled={!importPath.trim() || importingBackup}
            prefix={importingBackup ? <Spinner /> : undefined}
            onClick={() => {
              const path = importPath.trim();
              if (!path) return;
              setImportConfirmTarget({ kind: "path", path });
            }}
          >
            Restore path
          </Button>
        </div>
        <ConfirmDialog
          open={!!importConfirmTarget}
          title="Restore full Fabric backup?"
          description={`This will overwrite your current Fabric configuration, skills, sessions, and data with the contents of ${backupImportLabel(importConfirmTarget)}. This cannot be undone.`}
          destructive
          confirmLabel="Restore"
          cancelLabel="Cancel"
          onCancel={() => setImportConfirmTarget(null)}
          onConfirm={() => {
            const target = importConfirmTarget;
            setImportConfirmTarget(null);
            if (target) void runBackupImport(target);
          }}
        />
      </CardContent>
    </Card>
  );
}
