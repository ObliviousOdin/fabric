import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@nous-research/ui/ui/components/dialog";

export interface LearnSkillDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * "Learn a skill" flow (K6, behavior frozen — N17). Open-ended: dir + URL +
 * free-text inputs are composed into a single-line /learn command and
 * handed to the chat. /learn resolves to a normal agent turn
 * (command.dispatch → send), so the live agent gathers the sources with its
 * own tools and authors the skill via skill_manage. No backend distill
 * endpoint — one code path with the CLI/TUI/gateway /learn.
 */
export function LearnSkillDialog({ open, onOpenChange }: LearnSkillDialogProps) {
  const navigate = useNavigate();
  const [learnDir, setLearnDir] = useState("");
  const [learnUrl, setLearnUrl] = useState("");
  const [learnText, setLearnText] = useState("");

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (next) {
        // Fresh inputs on every open (mirrors the pre-split openLearn()).
        setLearnDir("");
        setLearnUrl("");
        setLearnText("");
      }
      onOpenChange(next);
    },
    [onOpenChange],
  );

  const submitLearn = useCallback(() => {
    const segs: string[] = [];
    const dir = learnDir.trim();
    const url = learnUrl.trim();
    const text = learnText.trim();
    if (dir) segs.push(`local source: ${dir}`);
    if (url) segs.push(`URL: ${url}`);
    if (text) segs.push(text);
    // Flatten to a single line — the chat composer submits on the first Enter.
    const composed = segs.join("; ").replace(/\s*\n\s*/g, " ").trim();
    if (!composed) return;
    onOpenChange(false);
    navigate(`/chat?learn=${encodeURIComponent(composed)}`);
  }, [learnDir, learnUrl, learnText, navigate, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Learn a skill</DialogTitle>
          <DialogDescription>
            Point Fabric at anything and it will distill a reusable skill —
            following the house authoring standards. Fill in any combination
            below; the agent gathers the sources and writes the skill in chat.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2">
          <div className="grid gap-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Local file or directory
            </label>
            <Input
              placeholder="~/projects/some-sdk  (read with read_file / search_files)"
              value={learnDir}
              onChange={(e) => setLearnDir(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              URL
            </label>
            <Input
              placeholder="https://docs.example.com/api  (fetched with web_extract)"
              value={learnUrl}
              onChange={(e) => setLearnUrl(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Anything else — describe the workflow, paste notes, or say
              "what we just did"
            </label>
            <textarea
              className="min-h-[90px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="e.g. how I file an expense report: open the portal, …"
              value={learnText}
              onChange={(e) => setLearnText(e.target.value)}
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button ghost onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={submitLearn}
            prefix={<Sparkles />}
            disabled={!learnDir.trim() && !learnUrl.trim() && !learnText.trim()}
          >
            Learn it
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
