(function () {
  "use strict";

  const SDK = window.__FABRIC_PLUGIN_SDK__;
  const registry = window.__FABRIC_PLUGINS__;
  if (!SDK || !registry || typeof registry.register !== "function") return;

  const React = SDK.React;
  const h = React.createElement;
  const {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
  } = SDK.hooks;
  const {
    Badge,
    Button,
    Card,
    CardContent,
    Input,
    Label,
    Select,
    SelectOption,
  } = SDK.components;
  const Icons = SDK.icons || {};
  const Checkbox = SDK.components.Checkbox || function (props) {
    const next = Object.assign({}, props);
    const onCheckedChange = next.onCheckedChange;
    delete next.onCheckedChange;
    return h("input", Object.assign(next, {
      type: "checkbox",
      checked: !!props.checked,
      onChange: function (event) {
        if (onCheckedChange) onCheckedChange(event.target.checked);
      },
    }));
  };

  const API = "/api/plugins/achievements";
  const VALID_TABS = new Set(["achievements", "leaderboard"]);
  const TIER_ORDER = { Thread: 0, Weave: 1, Loom: 2 };
  const STATUS_LABELS = {
    unlocked: "Unlocked",
    in_progress: "In progress",
    locked: "Locked",
  };

  function icon(name, props) {
    const Component = Icons[name];
    if (!Component) return null;
    return h(Component, Object.assign({
      size: 16,
      strokeWidth: 1.8,
      "aria-hidden": true,
      focusable: false,
    }, props || {}));
  }

  function objectValue(value) {
    return value && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  }

  function stringValue(value, fallback, maxLength) {
    if (typeof value !== "string") return fallback || "";
    const normalized = value.trim();
    return normalized.slice(0, maxLength || 240);
  }

  function numberValue(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : (fallback || 0);
  }

  function countValue(value) {
    return Math.max(0, Math.floor(numberValue(value, 0)));
  }

  function utf8ByteLength(value) {
    if (typeof TextEncoder === "function") {
      return new TextEncoder().encode(value).length;
    }
    let bytes = 0;
    for (let index = 0; index < value.length; index += 1) {
      const code = value.charCodeAt(index);
      if (code <= 0x7f) bytes += 1;
      else if (code <= 0x7ff) bytes += 2;
      else if (code >= 0xd800 && code <= 0xdbff && index + 1 < value.length) {
        const next = value.charCodeAt(index + 1);
        if (next >= 0xdc00 && next <= 0xdfff) {
          bytes += 4;
          index += 1;
        } else {
          bytes += 3;
        }
      } else {
        bytes += 3;
      }
    }
    return bytes;
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function titleCase(value) {
    const text = stringValue(value, "Other", 80).replace(/[_-]+/g, " ");
    return text.replace(/\b\w/g, function (letter) { return letter.toUpperCase(); });
  }

  function formatNumber(value) {
    try { return new Intl.NumberFormat().format(numberValue(value, 0)); }
    catch (_) { return String(numberValue(value, 0)); }
  }

  function formatDate(value) {
    if (value == null || value === "") return "Not yet";
    let date;
    if (typeof value === "number") {
      date = new Date(value < 100000000000 ? value * 1000 : value);
    } else {
      date = new Date(value);
    }
    if (Number.isNaN(date.getTime())) return "Unknown";
    try {
      return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
    } catch (_) {
      return date.toLocaleString();
    }
  }

  function parseApiErrorMessage(error) {
    const raw = error && error.message ? String(error.message) : String(error || "Request failed");
    const match = raw.match(/^\d{3}:\s*(.*)$/s);
    const body = match ? match[1] : raw;
    try {
      const payload = JSON.parse(body);
      if (payload && typeof payload.detail === "string") return payload.detail;
      if (payload && payload.detail && typeof payload.detail.message === "string") {
        return payload.detail.message;
      }
    } catch (_) { /* The SDK may return a plain-text error. */ }
    return body || "Request failed";
  }

  function selectChangeHandler(setter) {
    return {
      onValueChange: setter,
      onChange: function (event) {
        if (event && event.target) setter(event.target.value);
      },
    };
  }

  function normalizeTier(value) {
    const requested = stringValue(value, "Thread", 16).toLowerCase();
    if (requested === "loom") return "Loom";
    if (requested === "weave") return "Weave";
    return "Thread";
  }

  // The API deliberately exposes one compact shape. Normalization here only
  // bounds untrusted display values and flattens tracks for card rendering.
  function normalizeSummary(payload) {
    const root = objectValue(payload);
    if (!root || !Array.isArray(root.tracks)) {
      throw new Error("The local summary response is missing achievement tracks.");
    }

    const achievements = [];
    root.tracks.forEach(function (trackValue, trackIndex) {
      const track = objectValue(trackValue);
      if (!track || !Array.isArray(track.milestones)) return;
      const trackId = stringValue(track.id, "track-" + trackIndex, 100);
      const category = stringValue(track.category, "Other", 80);
      const metric = stringValue(track.metric, "", 120);
      const currentValue = Math.max(0, numberValue(track.value, 0));

      track.milestones.forEach(function (milestoneValue, milestoneIndex) {
        const milestone = objectValue(milestoneValue);
        if (!milestone) return;
        const threshold = Math.max(1, numberValue(milestone.threshold, 1));
        const earned = milestone.earned === true;
        const progress = clamp(numberValue(milestone.progress, earned ? 1 : 0), 0, 1);
        achievements.push({
          id: stringValue(
            milestone.id,
            trackId + "-milestone-" + milestoneIndex,
            140,
          ),
          trackId: trackId,
          trackTitle: stringValue(track.title, titleCase(trackId), 160),
          title: stringValue(milestone.title, "Untitled milestone", 180),
          description: stringValue(milestone.description, "", 1200),
          category: category,
          metric: metric,
          currentValue: currentValue,
          threshold: threshold,
          tier: normalizeTier(milestone.tier),
          points: countValue(milestone.points),
          earned: earned,
          earnedAt: milestone.earned_at || null,
          progress: progress,
          status: earned ? "unlocked" : (progress > 0 ? "in_progress" : "locked"),
        });
      });
    });

    achievements.sort(function (left, right) {
      const tier = TIER_ORDER[left.tier] - TIER_ORDER[right.tier];
      if (tier) return tier;
      const category = left.category.localeCompare(right.category);
      if (category) return category;
      return left.threshold - right.threshold;
    });

    return {
      schemaVersion: countValue(root.schema_version),
      generatedAt: root.generated_at || null,
      score: countValue(root.score),
      earnedCount: countValue(root.earned_count),
      totalPoints: countValue(root.total_points),
      metrics: objectValue(root.metrics) || {},
      achievements: achievements,
      privacy: objectValue(root.privacy) || {},
      newlyEarned: Array.isArray(root.newly_earned) ? root.newly_earned : [],
    };
  }

  function normalizeShareCard(cardValue) {
    const card = objectValue(cardValue);
    if (!card) return null;
    const cardId = stringValue(card.card_id, "", 240);
    if (!cardId) return null;
    const categoryTotals = objectValue(card.category_totals) || {};
    return {
      schemaVersion: countValue(card.schema_version),
      cardId: cardId,
      displayName: stringValue(card.display_name, "Unnamed profile", 120),
      generatedAt: card.generated_at || null,
      score: countValue(card.score),
      earnedCount: countValue(card.earned_count),
      categoryTotals: categoryTotals,
      achievementIds: Array.isArray(card.achievement_ids)
        ? card.achievement_ids.map(function (id) { return stringValue(id, "", 140); }).filter(Boolean)
        : [],
    };
  }

  function normalizeLeaderboard(payload) {
    const root = objectValue(payload);
    if (!root || !Array.isArray(root.entries)) {
      throw new Error("The local leaderboard response is missing entries.");
    }
    const entries = root.entries.map(function (entryValue) {
      const entry = objectValue(entryValue);
      if (!entry) return null;
      const card = normalizeShareCard(entry.card);
      if (!card) return null;
      if (entry.origin !== "local_profile" && entry.origin !== "self_reported_import") {
        return null;
      }
      const origin = entry.origin;
      return {
        origin: origin,
        isCurrentProfile: origin === "local_profile" && entry.is_current_profile === true,
        card: card,
      };
    }).filter(Boolean);

    entries.sort(function (left, right) {
      const score = right.card.score - left.card.score;
      if (score) return score;
      const earned = right.card.earnedCount - left.card.earnedCount;
      if (earned) return earned;
      if (left.isCurrentProfile !== right.isCurrentProfile) {
        return left.isCurrentProfile ? -1 : 1;
      }
      return left.card.displayName.localeCompare(right.card.displayName);
    });

    return {
      schemaVersion: countValue(root.schema_version),
      entries: entries,
      skippedLocalProfiles: countValue(root.skipped_local_profiles),
      privacy: objectValue(root.privacy) || {},
    };
  }

  function tabFromLocation(location) {
    try {
      const search = location && typeof location.search === "string"
        ? location.search
        : window.location.search;
      const requested = new URLSearchParams(search).get("tab");
      return VALID_TABS.has(requested) ? requested : "achievements";
    } catch (_) {
      return "achievements";
    }
  }

  function writeTabToRoute(tab, mode, navigate, routedLocation) {
    try {
      const routed = routedLocation && typeof navigate === "function";
      const pathname = routed ? routedLocation.pathname : window.location.pathname;
      const search = routed ? routedLocation.search : window.location.search;
      const hash = routed ? routedLocation.hash : window.location.hash;
      const params = new URLSearchParams(search || "");
      params.set("tab", tab);
      const query = params.toString();
      const next = pathname + (query ? "?" + query : "") + (hash || "");
      const current = routed
        ? routedLocation.pathname + routedLocation.search + routedLocation.hash
        : window.location.pathname + window.location.search + window.location.hash;
      if (next === current) return;
      if (routed) {
        navigate(next, { replace: mode !== "push" });
        return;
      }
      const method = mode === "push" ? "pushState" : "replaceState";
      const priorState = window.history.state;
      const nextState = priorState && typeof priorState === "object"
        ? Object.assign({}, priorState)
        : {};
      window.history[method](nextState, "", next);
    } catch (_) { /* History can be unavailable in embedded contexts. */ }
  }

  function ErrorPanel(props) {
    return h("section", { className: "fabric-achievements-error", role: "alert" },
      h("div", { className: "fabric-achievements-error-icon" }, icon("AlertTriangle")),
      h("div", null,
        h("h2", null, props.title || "Something went wrong"),
        h("p", null, props.message),
        props.onRetry
          ? h(Button, { type: "button", size: "sm", onClick: props.onRetry },
              icon("RotateCcw"), "Try again")
          : null,
      ),
    );
  }

  class ErrorBoundary extends React.Component {
    constructor(props) {
      super(props);
      this.state = { error: null };
    }
    static getDerivedStateFromError(error) { return { error: error }; }
    componentDidCatch(error, info) {
      // eslint-disable-next-line no-console
      console.error("Achievements plugin crashed:", error, info);
    }
    render() {
      if (!this.state.error) return this.props.children;
      return h("div", { className: "fabric-achievements-boundary" },
        h(ErrorPanel, {
          title: "Achievements could not render",
          message: String(this.state.error.message || this.state.error),
          onRetry: function () { window.location.reload(); },
        }),
      );
    }
  }

  function LoadingState(props) {
    return h("div", {
      className: "fabric-achievements-loading",
      role: "status",
      "aria-live": "polite",
    },
      h("span", { className: "fabric-achievements-loading-line is-short" }),
      h("span", { className: "fabric-achievements-loading-line" }),
      h("span", { className: "fabric-achievements-loading-grid" },
        h("span", null), h("span", null), h("span", null)),
      h("span", { className: "fabric-achievements-sr-only" }, props.label || "Loading achievements"),
    );
  }

  function PrivacyStrip(props) {
    return h("section", {
      className: "fabric-achievements-privacy",
      "aria-label": "Achievements privacy",
    },
      h("div", { className: "fabric-achievements-privacy-mark" }, icon("CheckCircle2", { size: 18 })),
      h("div", null,
        h("strong", null, "Device-only"),
        h("span", null,
          "No automatic uploads. Progress uses structured aggregate metrics and never reads conversation or file content."),
      ),
      props.leaderboard
        ? h("span", { className: "fabric-achievements-privacy-note" },
            "This table shows readable local profiles plus cards you explicitly import.")
        : null,
    );
  }

  function SummaryStats(props) {
    const summary = props.summary;
    const total = summary.achievements.length;
    const completion = summary.totalPoints > 0
      ? Math.round((summary.score / summary.totalPoints) * 100)
      : 0;
    const stats = [
      {
        label: "Score",
        value: formatNumber(summary.score),
        detail: formatNumber(summary.totalPoints) + " points available",
      },
      {
        label: "Milestones",
        value: formatNumber(summary.earnedCount) + " / " + formatNumber(total),
        detail: total === 1 ? "1 catalog milestone" : formatNumber(total) + " catalog milestones",
      },
      {
        label: "Completion",
        value: clamp(completion, 0, 100) + "%",
        detail: "Based on points earned",
      },
    ];
    return h("dl", { className: "fabric-achievements-stats", "aria-label": "Achievement summary" },
      stats.map(function (stat) {
        return h("div", { key: stat.label, className: "fabric-achievements-stat" },
          h("dt", null, stat.label),
          h("dd", { className: "fabric-achievements-stat-value" }, stat.value),
          h("dd", { className: "fabric-achievements-stat-detail" }, stat.detail),
        );
      }),
    );
  }

  function AchievementCard(props) {
    const achievement = props.achievement;
    const percent = Math.round(achievement.progress * 100);
    const ariaNow = achievement.earned
      ? achievement.threshold
      : Math.min(achievement.currentValue, achievement.threshold);
    const progressCopy = achievement.earned
      ? "Earned " + formatDate(achievement.earnedAt)
      : formatNumber(achievement.currentValue) + " of " + formatNumber(achievement.threshold);

    return h(Card, {
      className: "fabric-achievement-card tier-" + achievement.tier.toLowerCase() +
        " status-" + achievement.status,
      role: "article",
      "aria-labelledby": "fabric-achievement-title-" + achievement.id,
    },
      h(CardContent, { className: "fabric-achievement-card-content" },
        h("div", { className: "fabric-achievement-card-top" },
          h("div", { className: "fabric-achievement-badges" },
            h(Badge, { className: "fabric-achievement-tier" }, achievement.tier),
            h(Badge, { className: "fabric-achievement-category" }, titleCase(achievement.category)),
          ),
          h("span", { className: "fabric-achievement-points" },
            icon("Target", { size: 14 }),
            formatNumber(achievement.points) + " pt" + (achievement.points === 1 ? "" : "s"),
          ),
        ),
        h("div", { className: "fabric-achievement-card-copy" },
          h("h3", { id: "fabric-achievement-title-" + achievement.id }, achievement.title),
          achievement.description ? h("p", null, achievement.description) : null,
        ),
        h("div", { className: "fabric-achievement-progress-copy" },
          h("span", { className: "fabric-achievement-status" },
            h("span", { className: "fabric-achievement-status-dot", "aria-hidden": true }),
            STATUS_LABELS[achievement.status]),
          h("span", null, progressCopy),
        ),
        h("div", {
          className: "fabric-achievement-progress",
          role: "progressbar",
          "aria-label": achievement.title + " progress",
          "aria-valuemin": 0,
          "aria-valuemax": achievement.threshold,
          "aria-valuenow": ariaNow,
          "aria-valuetext": percent + "% — " + progressCopy,
        },
          h("span", {
            className: "fabric-achievement-progress-fill",
            style: { width: clamp(percent, 0, 100) + "%" },
          }),
        ),
        achievement.trackTitle
          ? h("p", { className: "fabric-achievement-track" }, achievement.trackTitle)
          : null,
      ),
    );
  }

  function AchievementsView(props) {
    const summary = props.summary;
    const [category, setCategory] = useState("all");
    const [status, setStatus] = useState("all");
    const categories = useMemo(function () {
      return Array.from(new Set(summary.achievements.map(function (item) {
        return item.category;
      }))).sort(function (left, right) { return left.localeCompare(right); });
    }, [summary]);
    const visible = useMemo(function () {
      return summary.achievements.filter(function (item) {
        return (category === "all" || item.category === category) &&
          (status === "all" || item.status === status);
      });
    }, [summary, category, status]);

    useEffect(function () {
      if (category !== "all" && categories.indexOf(category) < 0) setCategory("all");
    }, [categories, category]);

    if (!summary.achievements.length) {
      return h("section", {
        className: "fabric-achievements-empty",
        id: "fabric-achievements-panel-achievements",
        role: "tabpanel",
        "aria-labelledby": "fabric-achievements-tab-achievements",
      },
        icon("Target", { size: 20 }),
        h("h2", null, "No milestones are available"),
        h("p", null, "The local API did not provide a milestone catalog for this profile."),
      );
    }

    return h("section", {
      className: "fabric-achievements-catalog",
      id: "fabric-achievements-panel-achievements",
      role: "tabpanel",
      "aria-labelledby": "fabric-achievements-tab-achievements",
    },
      h("div", { className: "fabric-achievements-catalog-heading" },
        h("div", null,
          h("p", { className: "fabric-achievements-eyebrow" }, "Local catalog"),
          h("h2", null, "Milestones"),
          h("p", null, "Thread starts the habit, Weave builds range, and Loom marks sustained progress."),
        ),
        h("div", { className: "fabric-achievements-filters", "aria-label": "Filter achievements" },
          h("div", { className: "fabric-achievements-filter" },
            h(Label, { htmlFor: "fabric-achievements-category-filter" }, "Category"),
            h(Select, Object.assign({
              id: "fabric-achievements-category-filter",
              value: category,
              "aria-label": "Filter by category",
            }, selectChangeHandler(setCategory)),
              h(SelectOption, { value: "all" }, "All categories"),
              categories.map(function (item) {
                return h(SelectOption, { key: item, value: item }, titleCase(item));
              }),
            ),
          ),
          h("div", { className: "fabric-achievements-filter" },
            h(Label, { htmlFor: "fabric-achievements-status-filter" }, "Status"),
            h(Select, Object.assign({
              id: "fabric-achievements-status-filter",
              value: status,
              "aria-label": "Filter by status",
            }, selectChangeHandler(setStatus)),
              h(SelectOption, { value: "all" }, "All statuses"),
              h(SelectOption, { value: "unlocked" }, "Unlocked"),
              h(SelectOption, { value: "in_progress" }, "In progress"),
              h(SelectOption, { value: "locked" }, "Locked"),
            ),
          ),
        ),
      ),
      h("p", { className: "fabric-achievements-results", role: "status", "aria-live": "polite" },
        visible.length === 1 ? "1 milestone shown" : visible.length + " milestones shown"),
      visible.length
        ? h("div", { className: "fabric-achievements-grid" },
            visible.map(function (achievement) {
              return h(AchievementCard, { key: achievement.id, achievement: achievement });
            }))
        : h("div", { className: "fabric-achievements-empty is-filtered" },
            icon("Filter", { size: 20 }),
            h("h3", null, "No milestones match"),
            h("p", null, "Choose a different category or status."),
            h(Button, {
              type: "button",
              size: "sm",
              onClick: function () { setCategory("all"); setStatus("all"); },
            }, "Clear filters"),
          ),
    );
  }

  function ShareCardPanel(props) {
    const earned = useMemo(function () {
      return props.summary.achievements.filter(function (item) { return item.earned; });
    }, [props.summary]);
    const [displayName, setDisplayName] = useState("");
    const [selectedIds, setSelectedIds] = useState(function () { return new Set(); });
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [output, setOutput] = useState("");
    const [copyStatus, setCopyStatus] = useState("");
    const outputRef = useRef(null);

    useEffect(function () {
      setOutput("");
      setCopyStatus("");
    }, [props.summary.generatedAt, props.summary.score]);

    function toggleAchievement(id, checked) {
      const next = new Set(selectedIds);
      if (checked) {
        if (next.size >= 5 && !next.has(id)) {
          setError("Choose at most five achievement highlights.");
          return;
        }
        next.add(id);
      } else {
        next.delete(id);
      }
      setError("");
      setOutput("");
      setCopyStatus("");
      setSelectedIds(next);
    }

    function generate(event) {
      event.preventDefault();
      const name = displayName.trim();
      if (!name || busy) return;
      const body = { display_name: name };
      if (selectedIds.size) body.achievement_ids = Array.from(selectedIds);
      setBusy(true);
      setError("");
      setOutput("");
      setCopyStatus("");
      SDK.fetchJSON(API + "/share-card", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(function (result) {
        const card = result && objectValue(result.card);
        if (!card) throw new Error("The local API did not return a share card.");
        setOutput(JSON.stringify(card, null, 2));
      }).catch(function (requestError) {
        setError(parseApiErrorMessage(requestError));
      }).finally(function () {
        setBusy(false);
      });
    }

    function copyOutput() {
      if (!output) return;
      setCopyStatus("");
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        navigator.clipboard.writeText(output).then(function () {
          setCopyStatus("Copied to clipboard.");
        }).catch(function () {
          if (outputRef.current) {
            outputRef.current.focus();
            outputRef.current.select();
          }
          setCopyStatus("Clipboard access was unavailable. The full card is selected for manual copy.");
        });
        return;
      }
      if (outputRef.current) {
        outputRef.current.focus();
        outputRef.current.select();
      }
      setCopyStatus("The full card is selected for manual copy.");
    }

    return h("section", { className: "fabric-achievements-share-panel" },
      h("div", { className: "fabric-achievements-panel-heading" },
        h("div", null,
          h("p", { className: "fabric-achievements-eyebrow" }, "Manual export"),
          h("h3", null, "Create a share card"),
          h("p", null, "Generate JSON on this device, inspect it, then decide where to copy it."),
        ),
        icon("ArrowRight", { size: 19 }),
      ),
      h("form", { onSubmit: generate },
        h("div", { className: "fabric-achievements-field" },
          h(Label, { htmlFor: "fabric-achievements-display-name" }, "Display name"),
          h(Input, {
            id: "fabric-achievements-display-name",
            value: displayName,
            maxLength: 40,
            placeholder: "Name shown on the card",
            autoComplete: "off",
            disabled: busy,
            onChange: function (event) {
              setDisplayName(event.target.value);
              setOutput("");
              setCopyStatus("");
            },
          }),
        ),
        h("details", { className: "fabric-achievements-highlights" },
          h("summary", null,
            "Achievement highlights",
            h("span", null, "Optional · up to 5"),
          ),
          earned.length
            ? h("div", { className: "fabric-achievements-highlight-list" },
                earned.map(function (achievement) {
                  const checked = selectedIds.has(achievement.id);
                  const disabled = busy || (!checked && selectedIds.size >= 5);
                  return h("label", { key: achievement.id },
                    h(Checkbox, {
                      checked: checked,
                      disabled: disabled,
                      onCheckedChange: function (value) {
                        toggleAchievement(achievement.id, value === true);
                      },
                    }),
                    h("span", null,
                      h("strong", null, achievement.title),
                      h("small", null, achievement.tier + " · " + achievement.points + " pts"),
                    ),
                  );
                }),
              )
            : h("p", { className: "fabric-achievements-help" },
                "Unlocked milestones will appear here. With no selection, the card omits achievement IDs."),
        ),
        error ? h("p", { className: "fabric-achievements-form-error", role: "alert" }, error) : null,
        h("div", { className: "fabric-achievements-form-actions" },
          h(Button, {
            type: "submit",
            size: "sm",
            disabled: busy || !displayName.trim(),
          }, icon("FileText"), busy ? "Generating…" : "Generate JSON"),
          h("span", null, "Nothing is uploaded."),
        ),
      ),
      output
        ? h("div", { className: "fabric-achievements-share-output" },
            h("div", null,
              h(Label, { htmlFor: "fabric-achievements-share-json" }, "Complete share-card JSON"),
              h(Button, { type: "button", size: "sm", onClick: copyOutput },
                icon("FileText"), "Copy"),
            ),
            h("textarea", {
              ref: outputRef,
              id: "fabric-achievements-share-json",
              readOnly: true,
              value: output,
              rows: 11,
              spellCheck: false,
              "aria-describedby": "fabric-achievements-copy-status",
            }),
            h("p", {
              id: "fabric-achievements-copy-status",
              className: "fabric-achievements-help",
              role: "status",
              "aria-live": "polite",
            }, copyStatus || "The field above is exactly the payload another Fabric device can import."),
          )
        : null,
    );
  }

  function ImportPanel(props) {
    const [input, setInput] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const maxBytes = countValue(props.maxBytes);

    function submit(event) {
      event.preventDefault();
      if (!input.trim() || busy) return;
      if (maxBytes > 0 && utf8ByteLength(input) > maxBytes) {
        setError("The share card exceeds the " + formatNumber(maxBytes) + " byte import limit.");
        return;
      }
      let card;
      try {
        card = JSON.parse(input);
      } catch (_) {
        setError("Paste one complete share-card JSON object.");
        return;
      }
      if (!objectValue(card) || !stringValue(card.card_id, "", 240)) {
        setError("The share card must be a JSON object with a card_id.");
        return;
      }
      const name = stringValue(card.display_name, "this profile", 120);
      if (!window.confirm(
        "Import the self-reported score for " + name + " onto this device? " +
        "A card with the same card_id will be updated.",
      )) return;

      setBusy(true);
      setError("");
      setNotice("");
      // Send the exact text the user reviewed. Re-serializing the parsed
      // object here would erase duplicate JSON keys before the backend's
      // strict parser gets a chance to reject them.
      props.onImport(input).then(function (result) {
        setInput("");
        setNotice(result && result.created === false
          ? "Updated the existing self-reported card."
          : "Imported the self-reported card.");
      }).catch(function (requestError) {
        setError(parseApiErrorMessage(requestError));
      }).finally(function () {
        setBusy(false);
      });
    }

    return h("section", { className: "fabric-achievements-import-panel" },
      h("div", { className: "fabric-achievements-panel-heading" },
        h("div", null,
          h("p", { className: "fabric-achievements-eyebrow" }, "Explicit import"),
          h("h3", null, "Add a peer card"),
          h("p", null, "Paste JSON someone chose to share. Imported scores remain self-reported."),
        ),
        icon("FileText", { size: 19 }),
      ),
      h("form", { onSubmit: submit },
        h(Label, { htmlFor: "fabric-achievements-import-json" }, "Share-card JSON"),
        h("textarea", {
          id: "fabric-achievements-import-json",
          value: input,
          rows: 7,
          placeholder: "Paste the complete JSON object",
          spellCheck: false,
          onChange: function (event) {
            setInput(event.target.value);
            setError("");
            setNotice("");
          },
        }),
        error ? h("p", { className: "fabric-achievements-form-error", role: "alert" }, error) : null,
        notice ? h("p", {
          className: "fabric-achievements-form-notice",
          role: "status",
          "aria-live": "polite",
        }, notice) : null,
        h("div", { className: "fabric-achievements-form-actions" },
          h(Button, {
            type: "submit",
            size: "sm",
            disabled: busy || !input.trim(),
          }, icon("ArrowRight"), busy ? "Importing…" : "Review and import"),
          h("span", null, maxBytes > 0
            ? formatNumber(maxBytes) + " byte limit · confirmation required."
            : "Confirmation required."),
        ),
      ),
    );
  }

  function categorySummary(categoryTotals) {
    const parts = Object.keys(categoryTotals).sort().map(function (category) {
      return titleCase(category) + " " + formatNumber(categoryTotals[category]);
    });
    return parts.length ? parts.join(" · ") : "—";
  }

  function LeaderboardTable(props) {
    if (!props.model.entries.length) {
      return h("div", { className: "fabric-achievements-empty" },
        icon("Users", { size: 20 }),
        h("h3", null, "No local profiles or imported cards"),
        h("p", null, "No readable local profile cards or explicitly imported cards were returned."),
      );
    }
    return h("div", {
      className: "fabric-achievements-table-scroll",
      role: "region",
      "aria-label": "Local achievement leaderboard",
      tabIndex: 0,
    },
      h("table", null,
        h("caption", { className: "fabric-achievements-sr-only" },
          "Local achievement leaderboard with self-reported imported cards"),
        h("thead", null,
          h("tr", null,
            h("th", { scope: "col" }, "Rank"),
            h("th", { scope: "col" }, "Profile"),
            h("th", { scope: "col" }, "Score"),
            h("th", { scope: "col" }, "Earned"),
            h("th", { scope: "col" }, "Categories"),
            h("th", { scope: "col" }, "Source"),
            h("th", { scope: "col" }, "Generated"),
            h("th", { scope: "col" }, h("span", { className: "fabric-achievements-sr-only" }, "Actions")),
          ),
        ),
        h("tbody", null,
          props.model.entries.map(function (entry, index) {
            const card = entry.card;
            const imported = entry.origin === "self_reported_import";
            return h("tr", { key: entry.origin + "-" + card.cardId },
              h("td", { className: "fabric-achievements-rank" }, index + 1),
              h("th", { scope: "row" },
                h("span", { className: "fabric-achievements-profile-name" },
                  card.displayName,
                  entry.isCurrentProfile ? h(Badge, null, "Current") : null,
                ),
                h("span", { className: "fabric-achievements-card-id", title: card.cardId }, card.cardId),
              ),
              h("td", { className: "fabric-achievements-score" }, formatNumber(card.score)),
              h("td", null, formatNumber(card.earnedCount)),
              h("td", { className: "fabric-achievements-categories" }, categorySummary(card.categoryTotals)),
              h("td", null,
                h(Badge, { className: imported ? "is-imported" : "is-local" },
                  imported ? "Self-reported" : (entry.isCurrentProfile ? "Local · active" : "Local · read-only")),
              ),
              h("td", null, formatDate(card.generatedAt)),
              h("td", { className: "fabric-achievements-row-actions" },
                imported
                  ? h(Button, {
                      type: "button",
                      size: "sm",
                      disabled: props.deletingId === card.cardId,
                      onClick: function () { props.onDelete(entry); },
                      "aria-label": "Delete imported card for " + card.displayName,
                    }, icon("X"), props.deletingId === card.cardId ? "Removing…" : "Remove")
                  : h("span", { className: "fabric-achievements-read-only" }, "Read-only"),
              ),
            );
          }),
        ),
      ),
    );
  }

  function LeaderboardView(props) {
    if (props.loading && !props.model) {
      return h("section", {
        id: "fabric-achievements-panel-leaderboard",
        role: "tabpanel",
        "aria-labelledby": "fabric-achievements-tab-leaderboard",
      }, h(LoadingState, { label: "Loading the local leaderboard" }));
    }
    if (props.error && !props.model) {
      return h("section", {
        id: "fabric-achievements-panel-leaderboard",
        role: "tabpanel",
        "aria-labelledby": "fabric-achievements-tab-leaderboard",
      }, h(ErrorPanel, {
        title: "The local leaderboard could not load",
        message: props.error,
        onRetry: props.onRetry,
      }));
    }

    const maxBytes = props.summary && props.summary.privacy
      ? props.summary.privacy.share_card_max_bytes
      : 0;
    return h("section", {
      className: "fabric-achievements-leaderboard",
      id: "fabric-achievements-panel-leaderboard",
      role: "tabpanel",
      "aria-labelledby": "fabric-achievements-tab-leaderboard",
    },
      h("div", { className: "fabric-achievements-leaderboard-heading" },
        h("div", null,
          h("p", { className: "fabric-achievements-eyebrow" }, "On this device"),
          h("h2", null, "Local leaderboard"),
          h("p", null,
            "Local profiles are read-only here. Imported cards are explicitly shared and self-reported."),
        ),
        h(Button, {
          type: "button",
          size: "sm",
          disabled: props.loading,
          onClick: props.onRetry,
        }, icon("RotateCcw"), props.loading ? "Refreshing…" : "Refresh table"),
      ),
      props.error
        ? h("p", { className: "fabric-achievements-inline-error", role: "alert" }, props.error)
        : null,
      props.model && props.model.skippedLocalProfiles > 0
        ? h("p", { className: "fabric-achievements-skip-note", role: "status" },
            formatNumber(props.model.skippedLocalProfiles) + " local profile" +
            (props.model.skippedLocalProfiles === 1 ? " was" : "s were") +
            " skipped because its achievement data could not be read safely.")
        : null,
      h("div", { className: "fabric-achievements-sharing-grid" },
        h(ShareCardPanel, { summary: props.summary }),
        h(ImportPanel, { onImport: props.onImport, maxBytes: maxBytes }),
      ),
      props.model
        ? h(LeaderboardTable, {
            model: props.model,
            deletingId: props.deletingId,
            onDelete: props.onDelete,
          })
        : null,
    );
  }

  function AchievementsPage(hostProps) {
    const hostNavigate = hostProps && typeof hostProps.navigate === "function"
      ? hostProps.navigate
      : null;
    const hostLocation = hostProps && hostProps.location ? hostProps.location : null;
    const routedLocation = hostNavigate && hostLocation ? hostLocation : null;
    const hostLocationKey = routedLocation
      ? routedLocation.pathname + routedLocation.search + routedLocation.hash
      : null;
    const [activeTab, setActiveTab] = useState(function () { return tabFromLocation(routedLocation); });
    const [summary, setSummary] = useState(null);
    const [summaryLoading, setSummaryLoading] = useState(true);
    const [summaryError, setSummaryError] = useState("");
    const [refreshing, setRefreshing] = useState(false);
    const [notice, setNotice] = useState("");
    const [leaderboard, setLeaderboard] = useState(null);
    const [leaderboardLoading, setLeaderboardLoading] = useState(false);
    const [leaderboardError, setLeaderboardError] = useState("");
    const [deletingId, setDeletingId] = useState("");
    const tabRefs = useRef([]);
    const summaryRequestRef = useRef(0);
    const leaderboardRequestRef = useRef(0);

    const loadSummary = useCallback(function () {
      const requestId = ++summaryRequestRef.current;
      setSummaryLoading(true);
      setSummaryError("");
      return SDK.fetchJSON(API + "/summary").then(function (payload) {
        if (requestId !== summaryRequestRef.current) return null;
        const normalized = normalizeSummary(payload);
        setSummary(normalized);
        return normalized;
      }).catch(function (error) {
        if (requestId === summaryRequestRef.current) {
          setSummaryError(parseApiErrorMessage(error));
        }
        throw error;
      }).finally(function () {
        if (requestId === summaryRequestRef.current) setSummaryLoading(false);
      });
    }, []);

    const loadLeaderboard = useCallback(function () {
      const requestId = ++leaderboardRequestRef.current;
      setLeaderboardLoading(true);
      setLeaderboardError("");
      return SDK.fetchJSON(API + "/leaderboard").then(function (payload) {
        if (requestId !== leaderboardRequestRef.current) return null;
        const normalized = normalizeLeaderboard(payload);
        setLeaderboard(normalized);
        return normalized;
      }).catch(function (error) {
        if (requestId === leaderboardRequestRef.current) {
          setLeaderboardError(parseApiErrorMessage(error));
        }
        throw error;
      }).finally(function () {
        if (requestId === leaderboardRequestRef.current) setLeaderboardLoading(false);
      });
    }, []);

    useEffect(function () {
      loadSummary().catch(function () { /* Error state is rendered in-page. */ });
      return function () {
        summaryRequestRef.current += 1;
        leaderboardRequestRef.current += 1;
      };
    }, [loadSummary]);

    useEffect(function () {
      if (
        activeTab === "leaderboard" &&
        !leaderboard &&
        !leaderboardLoading &&
        !leaderboardError
      ) {
        loadLeaderboard().catch(function () { /* Error state is rendered in-page. */ });
      }
    }, [activeTab, leaderboard, leaderboardLoading, leaderboardError, loadLeaderboard]);

    useEffect(function () {
      function syncTab() { setActiveTab(tabFromLocation(routedLocation)); }
      if (hostLocationKey) {
        syncTab();
        return undefined;
      }
      window.addEventListener("popstate", syncTab);
      return function () { window.removeEventListener("popstate", syncTab); };
    }, [hostLocationKey]);

    function changeTab(tab) {
      if (!VALID_TABS.has(tab)) return;
      setActiveTab(tab);
      writeTabToRoute(tab, "push", hostNavigate, routedLocation);
    }

    function moveTab(event, index) {
      const tabs = ["achievements", "leaderboard"];
      let nextIndex = index;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        nextIndex = (index + 1) % tabs.length;
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        nextIndex = (index - 1 + tabs.length) % tabs.length;
      } else if (event.key === "Home") {
        nextIndex = 0;
      } else if (event.key === "End") {
        nextIndex = tabs.length - 1;
      } else {
        return;
      }
      event.preventDefault();
      changeTab(tabs[nextIndex]);
      if (tabRefs.current[nextIndex]) tabRefs.current[nextIndex].focus();
    }

    function refreshProgress() {
      if (refreshing) return;
      setRefreshing(true);
      setSummaryError("");
      setNotice("");
      SDK.fetchJSON(API + "/refresh", { method: "POST" }).then(function (payload) {
        const normalized = normalizeSummary(payload);
        summaryRequestRef.current += 1;
        setSummary(normalized);
        setSummaryLoading(false);
        const names = normalized.newlyEarned.map(function (item) {
          const milestone = objectValue(item);
          return milestone ? stringValue(milestone.title, "", 180) : "";
        }).filter(Boolean);
        setNotice(names.length
          ? "Newly earned: " + names.join(", ") + "."
          : "Progress refreshed from local aggregate metrics.");
        if (leaderboard || activeTab === "leaderboard") {
          loadLeaderboard().catch(function () { /* Table keeps its prior rows. */ });
        }
      }).catch(function (error) {
        setSummaryError(parseApiErrorMessage(error));
      }).finally(function () {
        setRefreshing(false);
      });
    }

    function importCard(rawCard) {
      return SDK.fetchJSON(API + "/leaderboard/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: rawCard,
      }).then(function (result) {
        return loadLeaderboard().catch(function () { return null; }).then(function () {
          return result;
        });
      });
    }

    function deleteImported(entry) {
      const card = entry.card;
      if (!window.confirm(
        "Remove the imported self-reported card for " + card.displayName + " from this device?",
      )) return;
      setDeletingId(card.cardId);
      setLeaderboardError("");
      SDK.fetchJSON(API + "/leaderboard/" + encodeURIComponent(card.cardId), {
        method: "DELETE",
      }).then(function () {
        return loadLeaderboard();
      }).catch(function (error) {
        setLeaderboardError(parseApiErrorMessage(error));
      }).finally(function () {
        setDeletingId("");
      });
    }

    const tabs = [
      { id: "achievements", label: "Achievements", icon: "Target" },
      { id: "leaderboard", label: "Leaderboard", icon: "Users" },
    ];

    return h(ErrorBoundary, null,
      h("main", { className: "fabric-achievements" },
        h("header", { className: "fabric-achievements-header" },
          h("div", null,
            h("p", { className: "fabric-achievements-eyebrow" }, "Personal progress"),
            h("h1", null, "Achievements"),
            h("p", null, "Private milestones built from structured activity on this Fabric device."),
          ),
          h("div", { className: "fabric-achievements-header-actions" },
            summary
              ? h("span", null, icon("Clock3", { size: 14 }), "Updated " + formatDate(summary.generatedAt))
              : null,
            h(Button, {
              type: "button",
              size: "sm",
              disabled: refreshing || summaryLoading,
              onClick: refreshProgress,
            }, icon("RotateCcw"), refreshing ? "Refreshing…" : "Refresh progress"),
          ),
        ),
        h(PrivacyStrip, { leaderboard: activeTab === "leaderboard" }),
        notice
          ? h("p", {
              className: "fabric-achievements-notice",
              role: "status",
              "aria-live": "polite",
            }, icon("CheckCircle2", { size: 16 }), notice)
          : null,
        summaryError && summary
          ? h("p", { className: "fabric-achievements-inline-error", role: "alert" }, summaryError)
          : null,
        summary
          ? h(SummaryStats, { summary: summary })
          : summaryLoading
            ? h(LoadingState, { label: "Loading local achievement progress" })
            : h(ErrorPanel, {
                title: "Local progress could not load",
                message: summaryError || "The summary was unavailable.",
                onRetry: function () {
                  loadSummary().catch(function () { /* Error state is rendered in-page. */ });
                },
              }),
        summary
          ? h(React.Fragment, null,
              h("nav", { className: "fabric-achievements-tabs", "aria-label": "Achievement views" },
                h("div", { role: "tablist", "aria-label": "Achievement views" },
                  tabs.map(function (tab, index) {
                    const active = activeTab === tab.id;
                    return h("button", {
                      key: tab.id,
                      ref: function (node) { tabRefs.current[index] = node; },
                      id: "fabric-achievements-tab-" + tab.id,
                      type: "button",
                      role: "tab",
                      tabIndex: active ? 0 : -1,
                      "aria-selected": active,
                      "aria-controls": "fabric-achievements-panel-" + tab.id,
                      onClick: function () { changeTab(tab.id); },
                      onKeyDown: function (event) { moveTab(event, index); },
                    }, icon(tab.icon), tab.label);
                  }),
                ),
              ),
              activeTab === "achievements"
                ? h(AchievementsView, { summary: summary })
                : h(LeaderboardView, {
                    summary: summary,
                    model: leaderboard,
                    loading: leaderboardLoading,
                    error: leaderboardError,
                    deletingId: deletingId,
                    onRetry: function () {
                      loadLeaderboard().catch(function () { /* Error state is rendered in-page. */ });
                    },
                    onImport: importCard,
                    onDelete: deleteImported,
                  }),
            )
          : null,
      ),
    );
  }

  registry.register("achievements", AchievementsPage);
})();
