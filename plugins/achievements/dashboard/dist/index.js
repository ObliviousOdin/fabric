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

  const API = "/api/plugins/achievements";
  const VIEWS = ["today", "paths", "collection", "leaderboard"];
  const VIEW_SET = new Set(VIEWS);
  const COLLECTION_STATUSES = new Set(["earned", "active", "legacy"]);
  const BOARD_SET = new Set(["you", "profiles", "friendly"]);
  const LINKEDIN_QUEST_ID = "content.linkedin_launch";
  const MAX_TEXT = 1200;
  const VIEW_DEFS = [
    { id: "today", label: "Today", icon: "Target" },
    { id: "paths", label: "Paths", icon: "Workflow" },
    { id: "collection", label: "Collection", icon: "FileText" },
    { id: "leaderboard", label: "Leaderboard", icon: "CheckCircle2" },
  ];
  const BOARD_DEFS = [
    { id: "you", label: "You" },
    { id: "profiles", label: "Profiles" },
    { id: "friendly", label: "Friendly" },
  ];
  const OUTCOME_FALLBACKS = [
    {
      id: "finish_faster",
      label: "Finish work faster",
      description: "Turn a useful chat into a completed, tool-assisted result.",
      preferredPaths: ["conversation", "computer_use", "deep_work"],
    },
    {
      id: "build_agents",
      label: "Build with agents",
      description: "Delegate bounded work and learn to run a capable agent crew.",
      preferredPaths: ["agent_crew", "anywhere", "deep_work"],
    },
    {
      id: "create_content",
      label: "Create content",
      description: "Make images, research, and publish-ready drafts with Fabric.",
      preferredPaths: ["create", "skills", "conversation"],
    },
    {
      id: "automate_work",
      label: "Automate recurring work",
      description: "Turn a repeated task into a reliable Fabric automation.",
      preferredPaths: ["automate", "skills", "agent_crew"],
    },
  ];
  const PATH_FALLBACKS = [
    ["conversation", "Conversation craft", "Get from a first useful thread to durable, multi-step work."],
    ["agent_crew", "Agent crew", "Delegate, coordinate parallel agents, and complete a crew run."],
    ["deep_work", "Deep work", "Build sustained, meaningful work sessions without rewarding idle time."],
    ["model_lab", "Model lab", "Connect and use the right model for the job."],
    ["create", "Create", "Research, generate images, and prepare content for publishing."],
    ["computer_use", "Computer use", "Navigate the browser and complete safe computer-use workflows."],
    ["automate", "Automate", "Schedule reliable recurring work and inspect the result."],
    ["skills", "Skills", "Use, combine, and improve Fabric skills."],
    ["contributor", "Contributor", "Improve Fabric and share reusable patterns."],
    ["anywhere", "Fabric anywhere", "Use Fabric across the surfaces that fit your work."],
  ];
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
    return normalized.slice(0, maxLength || MAX_TEXT);
  }

  function numberValue(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : (fallback || 0);
  }

  function countValue(value) {
    return Math.max(0, Math.floor(numberValue(value, 0)));
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function listValue(value) {
    return Array.isArray(value) ? value : [];
  }

  function uniqueStrings(value, maximum) {
    const seen = new Set();
    const output = [];
    listValue(value).forEach(function (item) {
      const text = stringValue(item, "", 160);
      if (!text || seen.has(text) || output.length >= maximum) return;
      seen.add(text);
      output.push(text);
    });
    return output;
  }

  function titleCase(value) {
    const text = stringValue(value, "", 100).replace(/[._-]+/g, " ");
    return text.replace(/\b\w/g, function (letter) { return letter.toUpperCase(); });
  }

  function journeyWarningLabel(value) {
    const code = stringValue(value, "", 160);
    const labels = {
      observer_events_dropped: "Some local activity signals were dropped. Progress may update after a later successful action.",
      settings_invalid: "Journey settings could not be read, so safe local defaults are active.",
    };
    return labels[code] || titleCase(code);
  }

  function formatNumber(value) {
    try { return new Intl.NumberFormat().format(numberValue(value, 0)); }
    catch (_) { return String(numberValue(value, 0)); }
  }

  function rewardLabel(quest) {
    if (!quest) return "";
    return quest.momentum > 0
      ? formatNumber(quest.momentum) + " Momentum"
      : formatNumber(quest.xp) + " XP";
  }

  function celebrationNotice(journey, fallback) {
    const earned = journey ? journey.newlyEarned : [];
    if (!earned || !earned.length) return fallback || "";
    const mode = journey.tracking ? journey.tracking.celebrationMode : "standard";
    if (mode === "off") return "";
    if (mode === "quiet") {
      return formatNumber(earned.length) + " new unlock" + (earned.length === 1 ? "" : "s") + ".";
    }
    const names = earned.map(function (item) { return item.title; }).filter(Boolean);
    return names.length ? "Unlocked: " + names.join(", ") + "." : fallback || "";
  }

  function formatActiveMinutes(value) {
    const minutes = countValue(value);
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    if (!hours) return minutes + "m";
    return hours + "h" + (remainder ? " " + remainder + "m" : "");
  }

  function formatDate(value) {
    if (value == null || value === "") return "Not yet";
    const date = typeof value === "number"
      ? new Date(value < 100000000000 ? value * 1000 : value)
      : new Date(value);
    if (Number.isNaN(date.getTime())) return "Unknown";
    try {
      return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
    } catch (_) {
      return date.toLocaleDateString();
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

  function safeId(value) {
    return stringValue(value, "item", 140).replace(/[^a-zA-Z0-9_-]+/g, "-");
  }

  function internalRoute(value) {
    const route = stringValue(value, "", 3000);
    if (!route.startsWith("/") || route.startsWith("//")) return "";
    return route;
  }

  function createFreshId() {
    try {
      if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
      }
    } catch (_) { /* fall through */ }
    return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  }

  function chatRoute(draft) {
    const params = new URLSearchParams({
      fresh: createFreshId(),
      draft: stringValue(draft, "Help me complete this Fabric quest.", 8000),
    });
    return "/workspace/chat?" + params.toString();
  }

  function selectChangeHandler(setter) {
    return {
      onValueChange: setter,
      onChange: function (event) {
        if (event && event.target) setter(event.target.value);
      },
    };
  }

  function progressValue(value, fallbackLabel) {
    const progress = objectValue(value) || {};
    const target = Math.max(1, countValue(progress.target || progress.total || 1));
    const current = clamp(countValue(progress.current || progress.value), 0, target);
    return {
      current: current,
      target: target,
      label: stringValue(
        progress.label,
        fallbackLabel || formatNumber(current) + " of " + formatNumber(target),
        220,
      ),
    };
  }

  function normalizeAction(value, fallback) {
    const action = objectValue(value) || {};
    const base = objectValue(fallback) || {};
    const requestedKind = stringValue(action.kind || action.type || base.kind, "none", 24);
    const kind = requestedKind === "chat" || requestedKind === "route" ? requestedKind : "none";
    return {
      kind: kind,
      label: stringValue(action.label || base.label, kind === "none" ? "" : "Start", 100),
      route: internalRoute(action.route || action.path || base.route),
      draft: stringValue(action.draft || action.prompt || base.draft, "", 8000),
    };
  }

  function normalizeStatus(value, earned) {
    const status = stringValue(value, earned ? "completed" : "available", 32).toLowerCase();
    if (status === "complete" || status === "earned" || status === "unlocked") return "completed";
    if (status === "in_progress" || status === "in-progress") return "active";
    if (status === "unsupported" || status === "locked") return "unavailable";
    if (["available", "active", "completed", "unavailable", "preview", "snoozed"].indexOf(status) >= 0) {
      return status;
    }
    return earned ? "completed" : "available";
  }

  function normalizeQuest(value, index, pathId) {
    const item = objectValue(value);
    if (!item) return null;
    const id = stringValue(item.id || item.quest_id || item.achievement_id, "quest-" + index, 140);
    const earned = item.earned === true || item.completed === true;
    const status = normalizeStatus(item.status, earned);
    const rawProgress = objectValue(item.progress) || {
      current: item.current,
      target: item.target || item.threshold,
      label: item.progress_label,
    };
    let action = normalizeAction(item.action, {
      kind: item.action_kind,
      label: item.action_label,
      route: item.action_route,
      draft: item.action_draft,
    });
    let xp = countValue(item.xp || item.points);
    let confidence = stringValue(item.confidence, "observed", 40);
    if (id === LINKEDIN_QUEST_ID) {
      xp = 0;
      confidence = "self_attested";
      if (action.kind === "none") {
        action = normalizeAction({
          kind: "chat",
          label: "Draft in Chat",
          draft: "Help me draft a useful LinkedIn post. Ask for the audience, the idea, and the proof, then create a reviewable draft. Do not claim it has been published.",
        });
      }
    }
    return {
      id: id,
      pathId: stringValue(item.path_id || pathId, pathId || "", 100),
      capability: stringValue(item.capability, "", 100),
      title: stringValue(item.title, titleCase(id), 180),
      description: stringValue(item.description, "", MAX_TEXT),
      why: stringValue(item.why || item.recommendation_reason, "", 360),
      xp: xp,
      momentum: countValue(item.momentum),
      estimateMinutes: countValue(item.estimate_minutes || item.minutes),
      status: status,
      confidence: confidence,
      progress: progressValue(rawProgress),
      action: action,
      unavailableReason: stringValue(item.unavailable_reason || item.unsupported_reason, "", 360),
      earned: status === "completed" || earned,
      earnedAt: item.earned_at || item.completed_at || null,
      hidden: item.hidden === true,
      rankEligible: item.rank_eligible !== false && id !== LINKEDIN_QUEST_ID,
      snoozeable: item.snoozeable === true,
      rerollAvailable: item.reroll_available === true,
      evidence: objectValue(item.evidence) || {},
    };
  }

  function normalizeQuestList(value, maximum, pathId) {
    return listValue(value).map(function (item, index) {
      return normalizeQuest(item, index, pathId);
    }).filter(Boolean).slice(0, maximum);
  }

  function normalizePath(value, index) {
    const item = objectValue(value);
    if (!item) return null;
    const fallback = PATH_FALLBACKS[index] || ["path-" + index, "Capability path", "Learn this Fabric capability."];
    const id = stringValue(item.id || item.path_id, fallback[0], 100);
    const steps = normalizeQuestList(item.steps || item.achievements || item.quests, 80, id);
    const completed = steps.filter(function (step) { return step.status === "completed"; }).length;
    return {
      id: id,
      title: stringValue(item.title, fallback[1], 180),
      description: stringValue(item.description, fallback[2], MAX_TEXT),
      status: normalizeStatus(item.status, steps.length > 0 && completed === steps.length),
      progress: progressValue(item.progress || { current: completed, target: Math.max(1, steps.length) }),
      steps: steps,
      nextAchievementId: stringValue(item.next_achievement_id || item.next_quest_id, "", 140),
    };
  }

  function normalizePathList(value) {
    return listValue(value).map(normalizePath).filter(Boolean).slice(0, 30);
  }

  function linkedInQuestFallback() {
    return normalizeQuest({
      id: LINKEDIN_QUEST_ID,
      path_id: "create",
      capability: "content_publishing",
      title: "Publish a useful LinkedIn post",
      description: "Draft and review a post with Fabric, then publish it yourself when it is ready.",
      why: "Turn research and writing help into a real, reviewable outcome without pretending Fabric can verify the external publish.",
      xp: 0,
      estimate_minutes: 20,
      status: "preview",
      confidence: "self_attested",
      rank_eligible: false,
      progress: { current: 0, target: 1, label: "Publish and self-attest" },
      action: {
        kind: "chat",
        label: "Draft in Chat",
        draft: "Help me draft a useful LinkedIn post. Ask for the audience, the idea, and the proof, then create a reviewable draft. Do not claim it has been published.",
      },
    }, 0, "create");
  }

  function ensureLinkedInPath(paths) {
    const output = listValue(paths).slice();
    const createIndex = output.findIndex(function (path) { return path.id === "create"; });
    const linkedin = linkedInQuestFallback();
    if (createIndex < 0) {
      const fallback = PATH_FALLBACKS.find(function (path) { return path[0] === "create"; });
      output.push(normalizePath({
        id: "create",
        title: fallback ? fallback[1] : "Create",
        description: fallback ? fallback[2] : "Prepare useful creative work with Fabric.",
        status: "preview",
        steps: [linkedin],
      }, 4));
      return output;
    }
    const createPath = output[createIndex];
    if (createPath.steps.some(function (step) { return step.id === LINKEDIN_QUEST_ID; })) return output;
    output[createIndex] = Object.assign({}, createPath, {
      steps: createPath.steps.concat([linkedin]),
    });
    return output;
  }

  function normalizeTodayActivity(value) {
    const activity = objectValue(value);
    if (!activity) return null;
    const activeMinutes = countValue(
      activity.active_minutes != null
        ? activity.active_minutes
        : activity.meaningful_active_minutes != null
          ? activity.meaningful_active_minutes
          : activity.minutes,
    );
    const capMinutes = countValue(activity.cap_minutes || activity.daily_cap_minutes);
    return {
      activeMinutes: activeMinutes,
      capMinutes: capMinutes,
      meaningfulOutcomes: countValue(activity.meaningful_outcomes),
      activeDays7: countValue(activity.active_days_7),
      meaningfulOutcomes7: countValue(activity.meaningful_outcomes_7),
      label: stringValue(activity.label, "Meaningful active time", 120),
      note: stringValue(activity.note || activity.description, "Private, non-XP reflection", 240),
      capped: activity.capped === true || (capMinutes > 0 && activeMinutes >= capMinutes),
    };
  }

  function normalizeOutcome(value, index) {
    const item = objectValue(value);
    const fallback = OUTCOME_FALLBACKS[index] || OUTCOME_FALLBACKS[0];
    if (!item) return fallback;
    return {
      id: stringValue(item.id, fallback.id, 80),
      label: stringValue(item.label || item.title, fallback.label, 140),
      description: stringValue(item.description, fallback.description, 360),
      preferredPaths: uniqueStrings(
        item.preferred_paths || item.preferredPaths || fallback.preferredPaths,
        10,
      ),
    };
  }

  function normalizeLevel(value, fallbackLabel) {
    const level = objectValue(value) || {};
    const label = stringValue(level.label || value, fallbackLabel || "Explorer", 100);
    return {
      id: stringValue(level.id, label.toLowerCase().replace(/\s+/g, "-"), 80),
      label: label,
    };
  }

  function normalizeNextLevel(value) {
    const level = objectValue(value);
    if (!level) return null;
    return {
      id: stringValue(level.id, "next", 80),
      label: stringValue(level.label, "Next level", 100),
      xpRequired: Math.max(1, countValue(level.xp_required || level.xpRequired || level.threshold)),
      requirements: listValue(level.requirements).map(function (raw, index) {
        const item = objectValue(raw) || {};
        const target = Math.max(1, countValue(item.target || 1));
        const current = clamp(countValue(item.current), 0, target);
        return {
          id: stringValue(item.id, "requirement-" + index, 100),
          label: stringValue(item.label, "Complete the requirement", 180),
          current: current,
          target: target,
          met: item.met === true || current >= target,
        };
      }).slice(0, 12),
    };
  }

  function normalizeLeaderboardProfile(value, index, source) {
    const item = objectValue(value);
    if (!item) return null;
    const card = objectValue(item.card) || (item.card_id ? item : {});
    const level = normalizeLevel(item.level || item.rank, "Explorer");
    return {
      id: stringValue(item.id || item.profile_id || item.profile || card.card_id, source + "-" + index, 180),
      displayName: stringValue(item.display_name || item.name || card.display_name, "Local profile", 120),
      isCurrent: item.is_current_profile === true || item.is_current === true,
      xp: countValue(item.xp || item.mastery_xp),
      level: level,
      earnedCount: countValue(item.earned_count),
      breadth: countValue(item.breadth && item.breadth.current != null ? item.breadth.current : item.breadth),
      momentum: countValue(item.momentum && item.momentum.points != null ? item.momentum.points : item.momentum),
      source: source,
      legacyScore: card.score == null ? null : countValue(card.score),
      legacyEarnedCount: countValue(card.earned_count),
      generatedAt: item.generated_at || card.generated_at || null,
      cardId: stringValue(card.card_id, "", 180),
      achievementIds: uniqueStrings(card.achievement_ids, 5),
      categoryTotals: objectValue(card.category_totals) || {},
      warningCount: countValue(item.warning_count),
    };
  }

  function normalizeProjectedLeaderboard(value) {
    const root = objectValue(value);
    if (!root) return null;
    const rawYou = root.you;
    let you = Array.isArray(rawYou)
      ? normalizeLeaderboardProfile(rawYou[0], 0, "verified")
      : normalizeLeaderboardProfile(rawYou, 0, "verified");
    let profiles = listValue(root.profiles).map(function (item, index) {
      return normalizeLeaderboardProfile(item, index, "verified");
    }).filter(Boolean).slice(0, 100);
    if (!you) you = profiles.find(function (entry) { return entry.isCurrent; }) || null;
    profiles = profiles.filter(function (entry) {
      return !entry.isCurrent && (!you || entry.id !== you.id);
    });
    const friendly = listValue(root.friendly).map(function (item, index) {
      return normalizeLeaderboardProfile(item, index, "friendly");
    }).filter(Boolean).slice(0, 100);
    if (!you && !profiles.length && !friendly.length) return null;
    return {
      kind: "v2",
      you: you,
      profiles: profiles,
      friendly: friendly,
      skippedLocalProfiles: countValue(root.skipped_local_profiles),
      warningCount: countValue(root.warning_count),
    };
  }

  function normalizeJourney(payload) {
    const outer = objectValue(payload);
    const root = outer && objectValue(outer.journey) ? outer.journey : outer;
    if (!root || countValue(root.schema_version) < 2) {
      throw new Error("The guided Journey response is unavailable.");
    }
    const onboarding = objectValue(root.onboarding) || {};
    const mastery = objectValue(root.mastery) || {};
    const today = objectValue(root.today) || {};
    const collection = objectValue(root.collection) || {};
    const tracking = objectValue(root.tracking) || {};
    const starterRaw = objectValue(root.starter) || {};
    const paths = ensureLinkedInPath(normalizePathList(root.paths));
    const linkedinAllowed = function (quest) { return quest && quest.id !== LINKEDIN_QUEST_ID; };
    let primary = normalizeQuest(today.primary, 0, "");
    if (!linkedinAllowed(primary)) primary = null;
    const optional = normalizeQuestList(today.optional, 20, "").filter(linkedinAllowed).slice(0, 2);
    const weekly = normalizeQuest(today.weekly, 0, "");
    const selectedOutcome = stringValue(onboarding.selected_outcome, "", 80);
    const outcomes = listValue(onboarding.outcomes).map(normalizeOutcome).filter(Boolean);
    return {
      schemaVersion: countValue(root.schema_version),
      generatedAt: root.generated_at || null,
      profile: objectValue(root.profile) || {},
      onboarding: {
        isFirstRun: onboarding.is_first_run === true,
        selectedOutcome: selectedOutcome,
        outcomes: (outcomes.length ? outcomes : OUTCOME_FALLBACKS).slice(0, 8),
      },
      mastery: {
        xp: countValue(mastery.xp),
        level: normalizeLevel(mastery.level, "Explorer"),
        nextLevel: normalizeNextLevel(mastery.next_level),
        breadth: progressValue(mastery.breadth || { current: 0, target: 10 }, "Capability breadth"),
        earnedCount: countValue(mastery.earned_count),
      },
      starter: {
        id: stringValue(starterRaw.id, "starter", 100),
        status: normalizeStatus(starterRaw.status, false),
        stepIndex: countValue(starterRaw.step_index),
        totalSteps: Math.max(1, countValue(starterRaw.total_steps || listValue(starterRaw.steps).length || 3)),
        steps: normalizeQuestList(starterRaw.steps, 12, "conversation"),
        action: normalizeAction(starterRaw.action),
      },
      today: {
        primary: primary,
        optional: optional,
        weekly: weekly && weekly.id !== LINKEDIN_QUEST_ID ? weekly : null,
        momentum: objectValue(today.momentum) || {},
        recentWins: normalizeQuestList(today.recent_wins, 4, "").filter(linkedinAllowed).slice(0, 3),
        activePaths: normalizePathList(today.active_paths).slice(0, 2),
        activity: normalizeTodayActivity(today.activity || today.reflection),
      },
      paths: paths,
      collection: {
        earned: normalizeQuestList(collection.earned, 500, ""),
        active: normalizeQuestList(collection.active, 3, ""),
        discover: normalizeQuestList(collection.discover, 3, ""),
        legacy: normalizeQuestList(collection.legacy, 500, "legacy"),
      },
      tracking: {
        enabled: tracking.enabled !== false,
        activeTimeEnabled: tracking.active_time_enabled !== false,
        celebrationMode: ["standard", "quiet", "off"].indexOf(tracking.celebration_mode) >= 0
          ? tracking.celebration_mode
          : "standard",
        state: stringValue(tracking.state, tracking.enabled === false ? "paused" : "active", 40),
        sources: objectValue(tracking.sources) || {},
        retentionDays: countValue(tracking.raw_event_retention_days),
        droppedEvents: countValue(tracking.dropped_events),
        settingsInvalid: tracking.settings_invalid === true,
        allowedFields: uniqueStrings(tracking.allowed_fields, 80),
        excludedFields: uniqueStrings(tracking.excluded_fields, 80),
      },
      leaderboard: normalizeProjectedLeaderboard(root.leaderboard),
      warnings: uniqueStrings(root.warnings, 30),
      newlyEarned: normalizeQuestList(root.newly_earned || (outer && outer.newly_earned), 20, ""),
      privacy: objectValue(root.privacy) || {},
      legacyMode: false,
    };
  }

  function normalizeLegacySummary(payload) {
    const root = objectValue(payload);
    if (!root || !Array.isArray(root.tracks)) {
      throw new Error("The local summary response is missing achievement tracks.");
    }
    const legacy = [];
    root.tracks.forEach(function (rawTrack, trackIndex) {
      const track = objectValue(rawTrack);
      if (!track) return;
      const value = countValue(track.value);
      listValue(track.milestones).forEach(function (raw, index) {
        const milestone = objectValue(raw);
        if (!milestone) return;
        const threshold = Math.max(1, countValue(milestone.threshold || 1));
        legacy.push(normalizeQuest({
          id: milestone.id || "legacy-" + trackIndex + "-" + index,
          path_id: "legacy",
          title: milestone.title,
          description: milestone.description,
          xp: milestone.points,
          status: milestone.earned === true ? "completed" : (value > 0 ? "active" : "unavailable"),
          confidence: "historical_inferred",
          earned: milestone.earned === true,
          earned_at: milestone.earned_at,
          progress: {
            current: Math.min(value, threshold),
            target: threshold,
            label: formatNumber(Math.min(value, threshold)) + " of " + formatNumber(threshold),
          },
        }, index, "legacy"));
      });
    });
    return {
      score: countValue(root.score),
      earnedCount: countValue(root.earned_count),
      generatedAt: root.generated_at || null,
      legacy: legacy.filter(Boolean),
      privacy: objectValue(root.privacy) || {},
      warnings: uniqueStrings(root.warnings, 30),
      newlyEarned: listValue(root.newly_earned),
    };
  }

  function fallbackStarterSteps(legacy) {
    const earned = legacy.earnedCount;
    return [
      normalizeQuest({
        id: "conversation.first_thread",
        path_id: "conversation",
        title: "Start one useful chat",
        description: "Bring Fabric a real outcome you want to finish.",
        status: earned > 0 ? "completed" : "available",
        xp: 50,
        progress: { current: earned > 0 ? 1 : 0, target: 1, label: earned > 0 ? "Useful chat completed" : "Start one useful chat" },
        action: { kind: "chat", label: "Start in Chat", draft: "Help me complete one useful outcome today. Ask only the context you need, then help me finish it." },
      }, 0, "conversation"),
      normalizeQuest({
        id: "starter.tool_outcome",
        path_id: "conversation",
        title: "Complete a tool-assisted action",
        description: "Use Fabric to produce a concrete result, not just a reply.",
        status: earned > 1 ? "completed" : (earned > 0 ? "available" : "unavailable"),
        xp: 75,
        progress: { current: earned > 1 ? 1 : 0, target: 1 },
      }, 1, "conversation"),
      normalizeQuest({
        id: "agents.first_delegate",
        path_id: "agent_crew",
        title: "Delegate one bounded task",
        description: "Give a subagent a clear, independent piece of work.",
        status: earned > 2 ? "completed" : (earned > 1 ? "available" : "unavailable"),
        xp: 100,
        progress: { current: earned > 2 ? 1 : 0, target: 1 },
        action: { kind: "chat", label: "Try delegation", draft: "Help me split this task and delegate one bounded, independent subtask to a subagent." },
      }, 2, "agent_crew"),
    ];
  }

  function journeyFromLegacy(payload) {
    const legacy = normalizeLegacySummary(payload);
    const steps = fallbackStarterSteps(legacy);
    const next = steps.find(function (step) { return step.status !== "completed"; }) || null;
    const paths = PATH_FALLBACKS.map(function (path) {
      return normalizePath({ id: path[0], title: path[1], description: path[2], steps: [] }, 0);
    });
    return {
      schemaVersion: 1,
      generatedAt: legacy.generatedAt,
      profile: {},
      onboarding: {
        isFirstRun: legacy.earnedCount === 0,
        selectedOutcome: "",
        outcomes: OUTCOME_FALLBACKS,
      },
      mastery: {
        xp: legacy.score,
        level: normalizeLevel(null, "Legacy progress"),
        nextLevel: null,
        breadth: progressValue({ current: 0, target: 10, label: "Journey breadth starts with V2 tracking" }),
        earnedCount: legacy.earnedCount,
      },
      starter: {
        id: "starter",
        status: next ? "active" : "completed",
        stepIndex: steps.filter(function (step) { return step.status === "completed"; }).length,
        totalSteps: 3,
        steps: steps,
        action: next ? next.action : normalizeAction(null),
      },
      today: {
        primary: next,
        optional: [],
        weekly: null,
        momentum: {},
        recentWins: legacy.legacy.filter(function (item) { return item.earned; }).slice(-3).reverse(),
        activePaths: [],
        activity: null,
      },
      paths: paths,
      collection: {
        earned: [],
        active: [],
        discover: [],
        legacy: legacy.legacy,
      },
      tracking: {
        enabled: true,
        activeTimeEnabled: true,
        celebrationMode: "standard",
        state: "legacy_fallback",
        sources: { historical: legacy.legacy.length },
        retentionDays: 0,
        droppedEvents: 0,
        settingsInvalid: false,
        allowedFields: [],
        excludedFields: [],
      },
      leaderboard: null,
      warnings: legacy.warnings,
      newlyEarned: legacy.newlyEarned,
      privacy: legacy.privacy,
      legacyMode: true,
    };
  }

  function normalizeLegacyLeaderboard(payload) {
    const root = objectValue(payload);
    if (!root || !Array.isArray(root.entries)) {
      throw new Error("The local leaderboard response is missing entries.");
    }
    const local = [];
    const friendly = [];
    root.entries.forEach(function (raw, index) {
      const entry = objectValue(raw);
      if (!entry) return;
      const normalized = normalizeLeaderboardProfile(entry, index,
        entry.origin === "self_reported_import" ? "friendly" : "legacy_local");
      if (!normalized) return;
      normalized.isCurrent = entry.is_current_profile === true;
      if (entry.origin === "self_reported_import") friendly.push(normalized);
      else if (entry.origin === "local_profile") local.push(normalized);
    });
    local.sort(function (left, right) {
      return numberValue(right.legacyScore, 0) - numberValue(left.legacyScore, 0);
    });
    friendly.sort(function (left, right) {
      return numberValue(right.legacyScore, 0) - numberValue(left.legacyScore, 0);
    });
    return {
      kind: "legacy",
      you: local.find(function (entry) { return entry.isCurrent; }) || null,
      profiles: local.filter(function (entry) { return !entry.isCurrent; }),
      friendly: friendly,
      skippedLocalProfiles: countValue(root.skipped_local_profiles),
      warningCount: countValue(root.warning_count),
    };
  }

  function readRoute(location) {
    let search = "";
    try {
      search = location && typeof location.search === "string" ? location.search : window.location.search;
    } catch (_) { /* no browser history */ }
    const params = new URLSearchParams(search || "");
    const rawView = params.get("view");
    const legacyTab = params.get("tab");
    let view = VIEW_SET.has(rawView) ? rawView : "today";
    let migrate = false;
    if (!rawView && legacyTab === "achievements") {
      view = "collection";
      migrate = true;
    } else if (!rawView && legacyTab === "leaderboard") {
      view = "leaderboard";
      migrate = true;
    } else if (rawView && !VIEW_SET.has(rawView)) {
      view = "today";
      migrate = true;
    } else if (legacyTab) {
      migrate = true;
    }
    const status = COLLECTION_STATUSES.has(params.get("status")) ? params.get("status") : "earned";
    const board = BOARD_SET.has(params.get("board")) ? params.get("board") : "you";
    return {
      view: view,
      path: stringValue(params.get("path"), "", 100),
      status: status,
      board: board,
      focus: stringValue(params.get("focus"), "", 140),
      migrate: migrate,
    };
  }

  function writeRoute(changes, mode, navigate, location) {
    try {
      const routed = location && typeof navigate === "function";
      const pathname = routed ? location.pathname : window.location.pathname;
      const search = routed ? location.search : window.location.search;
      const hash = routed ? location.hash : window.location.hash;
      const params = new URLSearchParams(search || "");
      Object.keys(changes).forEach(function (key) {
        const value = changes[key];
        if (value == null || value === "") params.delete(key);
        else params.set(key, String(value));
      });
      params.delete("tab");
      const query = params.toString();
      const next = pathname + (query ? "?" + query : "") + (hash || "");
      const current = routed
        ? location.pathname + location.search + location.hash
        : window.location.pathname + window.location.search + window.location.hash;
      if (next === current) return;
      if (routed) {
        navigate(next, { replace: mode !== "push" });
      } else {
        window.history[mode === "push" ? "pushState" : "replaceState"](
          Object.assign({}, window.history.state || {}), "", next,
        );
        window.dispatchEvent(new PopStateEvent("popstate"));
      }
    } catch (_) { /* History may be unavailable in an embedded context. */ }
  }

  function ErrorPanel(props) {
    return h("section", { className: "fabric-achievements-error", role: "alert" },
      h("div", { className: "fabric-achievements-error-icon" }, icon("AlertTriangle")),
      h("div", null,
        h("h2", null, props.title || "Something went wrong"),
        h("p", null, props.message),
        props.onRetry ? h(Button, { type: "button", size: "sm", onClick: props.onRetry },
          icon("RotateCcw"), "Try again") : null,
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

  function LoadingState() {
    return h("div", {
      className: "fabric-achievements-loading",
      role: "status",
      "aria-live": "polite",
      "aria-label": "Loading your Fabric Journey",
    },
      h("span", { className: "fabric-achievements-loading-line is-short" }),
      h("span", { className: "fabric-achievements-loading-line" }),
      h("span", { className: "fabric-achievements-loading-quest" }),
      h("span", { className: "fabric-achievements-sr-only" }, "Loading your Fabric Journey"),
    );
  }

  function ProgressBar(props) {
    const progress = props.progress || progressValue(null);
    const percent = clamp(Math.round((progress.current / progress.target) * 100), 0, 100);
    return h("div", { className: "fabric-achievements-progress-wrap" },
      h("div", { className: "fabric-achievements-progress-copy" },
        h("span", null, props.label || "Progress"),
        h("span", null, progress.label),
      ),
      h("div", {
        className: "fabric-achievements-progress",
        role: "progressbar",
        "aria-label": props.ariaLabel || props.label || "Progress",
        "aria-valuemin": 0,
        "aria-valuemax": progress.target,
        "aria-valuenow": progress.current,
        "aria-valuetext": progress.label,
      }, h("span", { className: "fabric-achievements-progress-fill", style: { width: percent + "%" } })),
    );
  }

  function ConfidenceBadge(props) {
    const value = stringValue(props.value, "observed", 40);
    const labels = {
      observed: "Observed",
      aggregate_observed: "Aggregate observed",
      historical_inferred: "Historical credit",
      self_attested: "Self-attested",
      unavailable: "Unavailable",
    };
    return h(Badge, { className: "fabric-achievements-confidence is-" + safeId(value) },
      labels[value] || titleCase(value));
  }

  function StatusLabel(props) {
    const labels = {
      available: "Available",
      active: "In progress",
      completed: "Completed",
      unavailable: "Unavailable",
      preview: "Preview",
      snoozed: "Snoozed",
    };
    return h("span", { className: "fabric-achievements-status status-" + safeId(props.status) },
      h("span", { className: "fabric-achievements-status-mark", "aria-hidden": true }),
      labels[props.status] || titleCase(props.status));
  }

  function QuestAction(props) {
    const quest = props.quest;
    if (!quest || !quest.action || quest.action.kind === "none" || quest.status === "completed") return null;
    return h(Button, {
      type: "button",
      size: props.primary ? undefined : "sm",
      disabled: quest.status === "unavailable" || props.disabled,
      onClick: function () { props.onAction(quest); },
    }, quest.action.kind === "chat" ? icon("ArrowRight") : icon("ExternalLink"),
    quest.action.label || "Start");
  }

  function QuestRow(props) {
    const quest = props.quest;
    const linkedin = quest.id === LINKEDIN_QUEST_ID;
    const attesting = props.attestPendingId === quest.id;
    return h("article", {
      className: "fabric-achievements-quest-row status-" + safeId(quest.status),
      id: "fabric-quest-" + safeId(quest.id),
      "data-quest-id": quest.id,
      tabIndex: -1,
      "aria-labelledby": "fabric-quest-title-" + safeId(quest.id),
    },
      h("div", { className: "fabric-achievements-quest-thread", "aria-hidden": true },
        quest.status === "completed" ? icon("CheckCircle2", { size: 18 }) : icon("Circle", { size: 18 })),
      h("div", { className: "fabric-achievements-quest-body" },
        h("div", { className: "fabric-achievements-quest-heading" },
          h("div", null,
            h("h3", { id: "fabric-quest-title-" + safeId(quest.id) }, quest.title),
            h("div", { className: "fabric-achievements-meta" },
              h(StatusLabel, { status: quest.status }),
              h(ConfidenceBadge, { value: quest.confidence }),
              h("span", null, linkedin ? "0 rank XP" : formatNumber(quest.xp) + " XP"),
              quest.estimateMinutes ? h("span", null, "About " + quest.estimateMinutes + " min") : null,
            ),
          ),
          h(QuestAction, { quest: quest, onAction: props.onAction, disabled: props.busy }),
        ),
        quest.description ? h("p", null, quest.description) : null,
        quest.why ? h("p", { className: "fabric-achievements-why" }, "Why this: " + quest.why) : null,
        quest.status !== "unavailable"
          ? h(ProgressBar, { progress: quest.progress, ariaLabel: quest.title + " progress" })
          : quest.unavailableReason
            ? h("p", { className: "fabric-achievements-unavailable" }, quest.unavailableReason)
            : null,
        linkedin ? h("div", { className: "fabric-achievements-attest" },
          h("p", null, "Publishing cannot be verified locally. Draft and review in Chat, then mark it only after you publish it yourself."),
          attesting
            ? h("div", { className: "fabric-achievements-inline-actions", role: "group", "aria-label": "Confirm self-attested publish" },
                h(Button, { type: "button", size: "sm", disabled: props.busy, onClick: function () { props.onAttest(quest); } },
                  props.busy ? "Saving…" : "Confirm self-attested publish"),
                h(Button, { type: "button", size: "sm", ghost: true, disabled: props.busy, onClick: props.onCancelAttest }, "Cancel"),
              )
            : h(Button, { type: "button", size: "sm", outlined: true, onClick: function () { props.onBeginAttest(quest.id); } },
                "Mark as published"),
        ) : null,
      ),
    );
  }

  function PrimaryQuest(props) {
    const quest = props.quest;
    if (!quest) {
      return h("section", { className: "fabric-achievements-quiet-state" },
        h("h2", null, "Your next quest is being prepared"),
        h("p", null, "Explore a capability path while Fabric gathers enough local evidence for a useful recommendation."),
        h(Button, { type: "button", outlined: true, onClick: props.onExplore }, "Explore paths", icon("ArrowRight")),
      );
    }
    return h(Card, { className: "fabric-achievements-primary-quest" },
      h(CardContent, null,
        h("div", { className: "fabric-achievements-primary-copy" },
          h("p", { className: "fabric-achievements-eyebrow" }, props.eyebrow || "Continue your journey"),
          h("h2", null, quest.title),
          quest.description ? h("p", null, quest.description) : null,
          quest.why ? h("p", { className: "fabric-achievements-why" }, quest.why) : null,
          h("div", { className: "fabric-achievements-meta" },
            h(ConfidenceBadge, { value: quest.confidence }),
            h("span", null, rewardLabel(quest)),
            quest.estimateMinutes ? h("span", null, "About " + quest.estimateMinutes + " min") : null,
          ),
        ),
        h(ProgressBar, { progress: quest.progress, ariaLabel: quest.title + " progress" }),
        h("div", { className: "fabric-achievements-primary-actions" },
          h(QuestAction, { quest: quest, primary: true, onAction: props.onAction, disabled: props.busy }),
          props.onReroll && quest.rerollAvailable
            ? h(Button, { type: "button", size: "sm", outlined: true, disabled: props.busy, onClick: function () { props.onReroll("daily"); } },
                icon("RotateCcw"), "Swap quest")
            : null,
          props.onSnooze && quest.snoozeable && quest.status !== "snoozed"
            ? h(Button, { type: "button", size: "sm", ghost: true, disabled: props.busy, onClick: function () { props.onSnooze(quest); } },
                icon("Clock3"), "Snooze 7 days")
            : null,
        ),
      ),
    );
  }

  function OutcomePicker(props) {
    return h("fieldset", { className: "fabric-achievements-outcomes" },
      h("legend", null, "What would you like Fabric to help you do first?"),
      h("div", null, props.outcomes.map(function (outcome) {
        const selected = props.selected === outcome.id;
        return h("button", {
          key: outcome.id,
          type: "button",
          className: selected ? "is-selected" : "",
          "aria-pressed": selected,
          disabled: props.busy,
          onClick: function () { props.onSelect(outcome.id); },
        },
          h("strong", null, outcome.label),
          h("span", null, outcome.description),
          selected ? icon("CheckCircle2") : null,
        );
      })),
    );
  }

  function FirstRunToday(props) {
    const journey = props.journey;
    const starter = journey.starter;
    const actionQuest = starter.steps.find(function (step) {
      return step.status === "available" || step.status === "active";
    }) || starter.steps[0] || null;
    const action = starter.action.kind !== "none"
      ? Object.assign({}, actionQuest || {}, { action: starter.action })
      : actionQuest;
    const selectedOutcome = journey.onboarding.outcomes.find(function (outcome) {
      return outcome.id === journey.onboarding.selectedOutcome;
    }) || journey.onboarding.outcomes[0] || OUTCOME_FALLBACKS[0];
    const recommendedIds = selectedOutcome.preferredPaths || OUTCOME_FALLBACKS[0].preferredPaths;
    const recommended = recommendedIds.map(function (id) {
      return journey.paths.find(function (path) { return path.id === id; });
    }).filter(Boolean).slice(0, 3);
    return h("div", { className: "fabric-achievements-first-run" },
      h("section", { className: "fabric-achievements-first-run-intro" },
        h("p", { className: "fabric-achievements-eyebrow" }, "Your Fabric Journey"),
        h("h2", null, "Learn Fabric by doing"),
        h("p", null, "Choose an outcome, complete one real piece of work, and learn the capabilities that made it possible."),
      ),
      h(OutcomePicker, {
        outcomes: journey.onboarding.outcomes,
        selected: journey.onboarding.selectedOutcome,
        onSelect: props.onOutcome,
        busy: props.busy,
      }),
      h("section", { className: "fabric-achievements-starter", "aria-labelledby": "fabric-starter-title" },
        h("div", { className: "fabric-achievements-section-heading" },
          h("div", null,
            h("p", { className: "fabric-achievements-eyebrow" }, "Starter journey"),
            h("h2", { id: "fabric-starter-title" }, "Three steps to your first Fabric workflow"),
          ),
          h("span", null, Math.min(starter.stepIndex, starter.totalSteps) + " of " + starter.totalSteps),
        ),
        h("ol", null, starter.steps.map(function (step, index) {
          return h("li", { key: step.id, className: "status-" + safeId(step.status) },
            h("span", { "aria-hidden": true }, step.status === "completed" ? icon("CheckCircle2") : String(index + 1)),
            h("div", null,
              h("strong", null, step.title),
              h("p", null, step.description),
            ),
          );
        })),
        action ? h("div", { className: "fabric-achievements-starter-action" },
          h(QuestAction, { quest: action, primary: true, onAction: props.onAction, disabled: props.busy }),
          h("span", null, "The prompt is placed in Chat for you to review before sending."),
        ) : null,
      ),
      recommended.length ? h("section", { className: "fabric-achievements-recommended" },
        h("div", { className: "fabric-achievements-section-heading" },
          h("div", null, h("h2", null, "Recommended paths"), h("p", null, "Go deeper when the starter journey feels useful.")),
        ),
        h("div", null, recommended.map(function (path) {
          return h("button", { key: path.id, type: "button", onClick: function () { props.onPath(path.id); } },
            h("strong", null, path.title), h("span", null, path.description), icon("ArrowRight"));
        })),
      ) : null,
    );
  }

  function LevelSummary(props) {
    const mastery = props.mastery;
    const next = mastery.nextLevel;
    const target = next ? next.xpRequired : Math.max(1, mastery.xp || 1);
    const progress = progressValue({
      current: Math.min(mastery.xp, target),
      target: target,
      label: next
        ? formatNumber(Math.max(0, target - mastery.xp)) + " XP to " + next.label
        : "Highest current level reached",
    });
    return h("section", { className: "fabric-achievements-level", "aria-label": "Journey mastery" },
      h("div", null,
        h("p", { className: "fabric-achievements-eyebrow" }, "Current level"),
        h("h2", null, mastery.level.label),
        h("p", null, formatNumber(mastery.xp) + " mastery XP · " + mastery.breadth.label),
      ),
      h(ProgressBar, { progress: progress, label: next ? "Next level" : "Mastery", ariaLabel: "Level progress" }),
    );
  }

  function ReturningToday(props) {
    const today = props.journey.today;
    const momentum = today.momentum;
    return h("div", { className: "fabric-achievements-today" },
      h(LevelSummary, { mastery: props.journey.mastery }),
      today.activity && props.journey.tracking.activeTimeEnabled ? h("section", {
        className: "fabric-achievements-activity-reflection",
        "aria-label": "Today's meaningful active time",
      },
        h("div", null,
          h("p", { className: "fabric-achievements-eyebrow" }, "Today's rhythm"),
          h("strong", null, formatActiveMinutes(today.activity.activeMinutes)),
        ),
        h("div", null,
          h("span", null, today.activity.label + (today.activity.capped ? " · reflection cap reached" : "")),
          h("small", null,
            (today.activity.meaningfulOutcomes
              ? formatNumber(today.activity.meaningfulOutcomes) + " meaningful outcome" + (today.activity.meaningfulOutcomes === 1 ? "" : "s") + " today · "
              : "") +
            (today.activity.activeDays7
              ? formatNumber(today.activity.activeDays7) + " active day" + (today.activity.activeDays7 === 1 ? "" : "s") + " this week · "
              : "") + today.activity.note),
        ),
      ) : null,
      h(PrimaryQuest, {
        quest: today.primary,
        onAction: props.onAction,
        onSnooze: props.onSnooze,
        onReroll: props.onReroll,
        onExplore: props.onExplore,
        busy: props.busy,
      }),
      today.optional.length ? h("section", { className: "fabric-achievements-optional", "aria-labelledby": "fabric-optional-title" },
        h("div", { className: "fabric-achievements-section-heading" },
          h("div", null, h("h2", { id: "fabric-optional-title" }, "Also worth trying"), h("p", null, "Optional quests that build range without distracting from your next step.")),
        ),
        h("div", null, today.optional.slice(0, 2).map(function (quest) {
          return h(QuestRow, { key: quest.id, quest: quest, onAction: props.onAction, busy: props.busy });
        })),
      ) : null,
      h("div", { className: "fabric-achievements-today-grid" },
        h("section", { className: "fabric-achievements-weekly" },
          h("p", { className: "fabric-achievements-eyebrow" }, "Weekly expedition"),
          today.weekly
            ? h(React.Fragment, null,
                h("h2", null, today.weekly.title),
                h("p", null, today.weekly.description),
                h("p", { className: "fabric-achievements-why" }, rewardLabel(today.weekly)),
                h(ProgressBar, { progress: today.weekly.progress, ariaLabel: today.weekly.title + " progress" }),
                h(QuestAction, { quest: today.weekly, onAction: props.onAction, disabled: props.busy }),
                props.onReroll && today.weekly.rerollAvailable
                  ? h(Button, { type: "button", size: "sm", outlined: true, disabled: props.busy, onClick: function () { props.onReroll("weekly"); } },
                      icon("RotateCcw"), "Swap expedition")
                  : null,
              )
            : h(React.Fragment, null,
                h("h2", null, "A weekly quest will appear here"),
                h("p", null, "Fabric avoids inventing busywork when no useful cross-capability mission is available."),
              ),
        ),
        h("section", { className: "fabric-achievements-momentum" },
          h("p", { className: "fabric-achievements-eyebrow" }, "Momentum"),
          h("h2", null, formatNumber(momentum.points || 0) + " points"),
          h("p", null, momentum.next_checkpoint
            ? formatNumber(momentum.next_checkpoint) + " points to the next local season checkpoint."
            : "Momentum rewards useful return visits without punishing a day away."),
          momentum.season_id ? h("span", null, "Season " + stringValue(momentum.season_id, "", 80)) : null,
        ),
      ),
      today.recentWins.length ? h("section", { className: "fabric-achievements-recent" },
        h("div", { className: "fabric-achievements-section-heading" },
          h("div", null, h("h2", null, "Recent wins"), h("p", null, "Capabilities you have demonstrated locally.")),
        ),
        h("ol", null, today.recentWins.slice(0, 3).map(function (win) {
          return h("li", { key: win.id }, icon("CheckCircle2"), h("div", null,
            h("strong", null, win.title),
            h("span", null, win.earnedAt ? "Earned " + formatDate(win.earnedAt) : titleCase(win.capability)),
          ));
        })),
      ) : null,
      today.activePaths.length ? h("section", { className: "fabric-achievements-active-paths" },
        h("div", { className: "fabric-achievements-section-heading" },
          h("div", null, h("h2", null, "Active paths"), h("p", null, "Continue building depth in the capabilities already underway.")),
        ),
        h("div", null, today.activePaths.slice(0, 2).map(function (path) {
          return h("button", { key: path.id, type: "button", onClick: function () { props.onPath(path.id); } },
            h("strong", null, path.title),
            h("span", null, path.progress.label),
            icon("ArrowRight"));
        })),
      ) : null,
    );
  }

  function TodayView(props) {
    return h("section", {
      className: "fabric-achievements-view",
      id: "fabric-achievements-panel-today",
      role: "tabpanel",
      "aria-labelledby": "fabric-achievements-tab-today",
    }, props.journey.onboarding.isFirstRun || props.journey.starter.status !== "completed"
      ? h(FirstRunToday, props)
      : h(ReturningToday, props));
  }

  function PathsView(props) {
    const paths = props.journey.paths;
    const selected = paths.find(function (path) { return path.id === props.selectedPath; }) ||
      paths.find(function (path) { return path.status === "active"; }) || paths[0] || null;
    const pathRefs = useRef([]);

    function movePath(event, index) {
      if (!paths.length) return;
      let next = index;
      if (event.key === "ArrowDown" || event.key === "ArrowRight") next = (index + 1) % paths.length;
      else if (event.key === "ArrowUp" || event.key === "ArrowLeft") next = (index - 1 + paths.length) % paths.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = paths.length - 1;
      else return;
      event.preventDefault();
      props.onPath(paths[next].id);
      if (pathRefs.current[next]) pathRefs.current[next].focus();
    }

    return h("section", {
      className: "fabric-achievements-view fabric-achievements-paths",
      id: "fabric-achievements-panel-paths",
      role: "tabpanel",
      "aria-labelledby": "fabric-achievements-tab-paths",
    },
      h("div", { className: "fabric-achievements-view-intro" },
        h("p", { className: "fabric-achievements-eyebrow" }, "Capability curriculum"),
        h("h2", null, "Choose a path, then learn it by doing"),
        h("p", null, "Each path makes prerequisites, evidence quality, and the next useful step explicit."),
      ),
      paths.length ? h("div", { className: "fabric-achievements-path-layout" },
        h("nav", { "aria-label": "Capability paths" },
          h("ol", null, paths.map(function (path, index) {
            const active = selected && selected.id === path.id;
            return h("li", { key: path.id },
              h("button", {
                type: "button",
                ref: function (node) { pathRefs.current[index] = node; },
                "aria-current": active ? "step" : undefined,
                onClick: function () { props.onPath(path.id); },
                onKeyDown: function (event) { movePath(event, index); },
              },
                h("span", null, h("strong", null, path.title), h(StatusLabel, { status: path.status })),
                h("small", null, path.progress.label),
              ),
            );
          })),
        ),
        selected ? h("section", { className: "fabric-achievements-path-detail", "aria-labelledby": "fabric-path-title-" + safeId(selected.id) },
          h("div", { className: "fabric-achievements-path-heading" },
            h("div", null,
              h("p", { className: "fabric-achievements-eyebrow" }, "Selected path"),
              h("h2", { id: "fabric-path-title-" + safeId(selected.id) }, selected.title),
              h("p", null, selected.description),
            ),
            h("span", null, selected.progress.label),
          ),
          h(ProgressBar, { progress: selected.progress, ariaLabel: selected.title + " path progress" }),
          selected.steps.length ? h("div", { className: "fabric-achievements-path-steps" },
            selected.steps.map(function (quest) {
              return h(QuestRow, {
                key: quest.id,
                quest: quest,
                onAction: props.onAction,
                busy: props.busy,
                attestPendingId: props.attestPendingId,
                onBeginAttest: props.onBeginAttest,
                onCancelAttest: props.onCancelAttest,
                onAttest: props.onAttest,
              });
            }))
            : h("div", { className: "fabric-achievements-quiet-state is-compact" },
                h("h3", null, "Journey steps are not available yet"),
                h("p", null, props.journey.legacyMode
                  ? "Your Legacy progress is safe. Upgrade the local Journey backend to receive guided steps for this path."
                  : "This path is visible for orientation but has no supported quest on this profile yet."),
              ),
        ) : null,
      ) : h("div", { className: "fabric-achievements-quiet-state" },
          h("h2", null, "Capability paths are unavailable"),
          h("p", null, "Your existing achievements remain in Collection while the guided path catalog is unavailable."),
        ),
    );
  }

  function CollectionList(props) {
    if (!props.items.length) {
      return h("div", { className: "fabric-achievements-quiet-state is-compact" },
        h("h3", null, props.emptyTitle),
        h("p", null, props.emptyDescription));
    }
    return h("div", { className: "fabric-achievements-collection-list" },
      props.items.map(function (item) {
        return h("article", { key: item.id, className: "fabric-achievements-collection-row" },
          h("div", { className: "fabric-achievements-collection-mark", "aria-hidden": true },
            item.earned ? icon("CheckCircle2") : icon("Circle")),
          h("div", null,
            h("div", { className: "fabric-achievements-collection-heading" },
              h("h3", null, item.title),
              h("span", null, item.id === LINKEDIN_QUEST_ID ? "0 rank XP" : formatNumber(item.xp) + " XP"),
            ),
            item.description ? h("p", null, item.description) : null,
            h("div", { className: "fabric-achievements-meta" },
              h(StatusLabel, { status: item.status }),
              h(ConfidenceBadge, { value: item.confidence }),
              item.earnedAt ? h("span", null, "Earned " + formatDate(item.earnedAt)) : null,
            ),
            !item.earned && item.status !== "unavailable"
              ? h(ProgressBar, { progress: item.progress, ariaLabel: item.title + " progress" })
              : null,
          ),
        );
      }),
    );
  }

  function CollectionView(props) {
    const collection = props.journey.collection;
    const status = props.status;
    let content;
    if (status === "active") {
      content = h(React.Fragment, null,
        h("section", { "aria-labelledby": "fabric-collection-next" },
          h("div", { className: "fabric-achievements-section-heading" },
            h("div", null, h("h2", { id: "fabric-collection-next" }, "Up next"), h("p", null, "The three closest useful achievements.")),
          ),
          h(CollectionList, {
            items: collection.active.slice(0, 3),
            emptyTitle: "No achievement is close yet",
            emptyDescription: "Complete the starter journey and a useful next achievement will appear here.",
          }),
        ),
        h("section", { "aria-labelledby": "fabric-collection-discover" },
          h("div", { className: "fabric-achievements-section-heading" },
            h("div", null, h("h2", { id: "fabric-collection-discover" }, "Discover"), h("p", null, "A small set of capabilities outside your current path.")),
          ),
          h(CollectionList, {
            items: collection.discover.slice(0, 3),
            emptyTitle: "Nothing extra to recommend",
            emptyDescription: "Fabric keeps this list short instead of filling the page with locked badges.",
          }),
        ),
      );
    } else if (status === "legacy") {
      content = h("details", { className: "fabric-achievements-legacy", open: true },
        h("summary", null, "Legacy milestones (" + formatNumber(collection.legacy.length) + ")"),
        h("p", null, "Progress earned under the original aggregate catalog is preserved here and does not drive V2 recommendations."),
        h(CollectionList, {
          items: collection.legacy,
          emptyTitle: "No Legacy milestones",
          emptyDescription: "This profile has no preserved V1 milestone history.",
        }),
      );
    } else {
      content = h("section", { "aria-labelledby": "fabric-collection-earned" },
        h("div", { className: "fabric-achievements-section-heading" },
          h("div", null, h("h2", { id: "fabric-collection-earned" }, "Earned achievements"), h("p", null, "A durable local record of capabilities you have demonstrated.")),
        ),
        h(CollectionList, {
          items: collection.earned,
          emptyTitle: "Your first win will appear here",
          emptyDescription: "Start with Today. One useful completed workflow is enough to begin your collection.",
        }),
      );
    }
    return h("section", {
      className: "fabric-achievements-view fabric-achievements-collection",
      id: "fabric-achievements-panel-collection",
      role: "tabpanel",
      "aria-labelledby": "fabric-achievements-tab-collection",
    },
      h("div", { className: "fabric-achievements-view-intro" },
        h("p", { className: "fabric-achievements-eyebrow" }, "Capability record"),
        h("h2", null, "Collection"),
        h("p", null, "Earned work first, a bounded set of next steps, and preserved Legacy history."),
      ),
      h("nav", { className: "fabric-achievements-subnav", "aria-label": "Collection filter" },
        [
          ["earned", "Earned"],
          ["active", "Up next"],
          ["legacy", "Legacy"],
        ].map(function (item) {
          return h("button", {
            key: item[0], type: "button", "aria-current": status === item[0] ? "page" : undefined,
            onClick: function () { props.onStatus(item[0]); },
          }, item[1]);
        })),
      content,
    );
  }

  function ProfileRecord(props) {
    const item = props.item;
    const legacy = props.legacy || item.source === "legacy_local";
    return h("li", { className: "fabric-achievements-profile-record" },
      props.rank ? h("span", { className: "fabric-achievements-rank", "aria-label": "Rank " + props.rank }, props.rank) : null,
      h("div", { className: "fabric-achievements-profile-main" },
        h("div", null,
          h("strong", null, item.displayName),
          item.isCurrent ? h(Badge, null, "Current") : null,
          legacy ? h(Badge, { className: "is-legacy" }, "Legacy local snapshot") : null,
          item.source === "friendly" ? h(Badge, { className: "is-friendly" }, "Self-reported") : null,
        ),
        legacy
          ? h("p", null, "V1 score " + formatNumber(item.legacyScore || 0) + " · " + formatNumber(item.legacyEarnedCount) + " Legacy milestones")
          : item.source === "friendly"
            ? h("p", null, "Self-reported Legacy score " + formatNumber(item.legacyScore || 0) + " · " + formatNumber(item.legacyEarnedCount) + " milestones")
            : h("p", null, item.level.label + " · " + formatNumber(item.xp) + " XP · " + formatNumber(item.earnedCount) + " earned"),
      ),
      !legacy && item.source !== "friendly" ? h("dl", null,
        h("div", null, h("dt", null, "Breadth"), h("dd", null, formatNumber(item.breadth))),
        h("div", null, h("dt", null, "Momentum"), h("dd", null, formatNumber(item.momentum))),
      ) : null,
      props.onDelete ? h("div", { className: "fabric-achievements-record-actions" },
        props.pendingDelete
          ? h(React.Fragment, null,
              h(Button, { type: "button", size: "sm", disabled: props.busy, onClick: function () { props.onDelete(item); } },
                props.busy ? "Removing…" : "Confirm remove"),
              h(Button, { type: "button", size: "sm", ghost: true, disabled: props.busy, onClick: props.onCancelDelete }, "Cancel"),
            )
          : h(Button, { type: "button", size: "sm", outlined: true, onClick: function () { props.onBeginDelete(item.id); },
              "aria-label": "Remove imported card for " + item.displayName }, icon("X"), "Remove"),
      ) : null,
    );
  }

  function SharePanel(props) {
    const [displayName, setDisplayName] = useState("");
    const [output, setOutput] = useState("");
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const [copyStatus, setCopyStatus] = useState("");

    function generate() {
      if (!displayName.trim() || busy) return;
      setBusy(true);
      setError("");
      setCopyStatus("");
      SDK.fetchJSON(API + "/share-card", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName.trim() }),
      }).then(function (payload) {
        const root = objectValue(payload) || {};
        setOutput(JSON.stringify(root.card || {}, null, 2));
      }).catch(function (reason) {
        setError(parseApiErrorMessage(reason));
      }).finally(function () { setBusy(false); });
    }

    function copy() {
      if (!output) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(output).then(function () {
          setCopyStatus("Copied share card JSON.");
        }).catch(function () { setCopyStatus("Copy failed. Select the JSON manually."); });
      } else {
        setCopyStatus("Select the JSON and copy it manually.");
      }
    }

    return h("section", { className: "fabric-achievements-share-panel" },
      h("h3", null, "Share a local snapshot"),
      h("p", null, "Fabric generates readable JSON on this device. Nothing is uploaded automatically."),
      h(Label, { htmlFor: "fabric-achievements-display-name" }, "Display name"),
      h(Input, {
        id: "fabric-achievements-display-name", value: displayName, maxLength: 40,
        onChange: function (event) { setDisplayName(event.target.value); setOutput(""); },
      }),
      error ? h("p", { className: "fabric-achievements-form-error", role: "alert" }, error) : null,
      h(Button, { type: "button", size: "sm", disabled: busy || !displayName.trim(), onClick: generate },
        busy ? "Generating…" : "Generate share card"),
      output ? h("div", { className: "fabric-achievements-share-output" },
        h(Label, { htmlFor: "fabric-achievements-share-json" }, "Complete share-card JSON"),
        h("textarea", { id: "fabric-achievements-share-json", readOnly: true, value: output, rows: 7 }),
        h(Button, { type: "button", size: "sm", outlined: true, onClick: copy }, "Copy JSON"),
        h("p", { role: "status", "aria-live": "polite" }, copyStatus),
      ) : null,
    );
  }

  function ImportPanel(props) {
    const [input, setInput] = useState("");
    const [review, setReview] = useState(null);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);

    function reviewInput() {
      setError("");
      try {
        if (typeof TextEncoder === "function" && new TextEncoder().encode(input).length > 16 * 1024) {
          throw new Error("Share card exceeds 16 KiB.");
        }
        const parsed = JSON.parse(input);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Share card must be a JSON object.");
        const name = stringValue(parsed.display_name, "", 40);
        if (!name || !stringValue(parsed.card_id, "", 180)) throw new Error("Share card is missing its display name or card ID.");
        setReview({ displayName: name, score: countValue(parsed.score), raw: input });
      } catch (reason) {
        setReview(null);
        setError(parseApiErrorMessage(reason));
      }
    }

    function confirmImport() {
      if (!review || busy) return;
      setBusy(true);
      setError("");
      props.onImport(review.raw).then(function () {
        setInput("");
        setReview(null);
      }).catch(function (reason) {
        setError(parseApiErrorMessage(reason));
      }).finally(function () { setBusy(false); });
    }

    return h("section", { className: "fabric-achievements-import-panel" },
      h("h3", null, "Import a Friendly card"),
      h("p", null, "Imported cards are self-reported and never join verified profile rankings."),
      h(Label, { htmlFor: "fabric-achievements-import-json" }, "Share-card JSON"),
      h("textarea", {
        id: "fabric-achievements-import-json", value: input, rows: 7,
        onChange: function (event) { setInput(event.target.value); setReview(null); setError(""); },
      }),
      error ? h("p", { className: "fabric-achievements-form-error", role: "alert" }, error) : null,
      review ? h("div", { className: "fabric-achievements-import-review", role: "status" },
        h("strong", null, "Review " + review.displayName),
        h("span", null, "Self-reported Legacy score " + formatNumber(review.score) + "."),
        h("div", null,
          h(Button, { type: "button", size: "sm", disabled: busy, onClick: confirmImport }, busy ? "Importing…" : "Confirm import"),
          h(Button, { type: "button", size: "sm", ghost: true, disabled: busy, onClick: function () { setReview(null); } }, "Cancel"),
        ),
      ) : h(Button, { type: "button", size: "sm", outlined: true, disabled: !input.trim(), onClick: reviewInput }, "Review import"),
    );
  }

  function LeaderboardView(props) {
    const board = props.board;
    const model = props.model;
    let records = [];
    let intro = "";
    if (model) {
      if (board === "you") records = model.you ? [model.you] : [];
      else if (board === "profiles") records = model.profiles;
      else records = model.friendly;
    }
    if (board === "you") intro = model && model.kind === "legacy"
      ? "This is a preserved V1 local snapshot, not V2 mastery or a verified rank."
      : "Your private mastery record. It is compared only when you choose another board.";
    else if (board === "profiles") intro = model && model.kind === "legacy"
      ? "Readable local V1 profiles are shown as Legacy snapshots, not V2 mastery rankings."
      : "V2 mastery for readable profiles on this device. Friendly imports never enter this ranking.";
    else intro = "Explicitly imported, self-reported cards. Friendly scores are never mixed with verified local mastery.";

    return h("section", {
      className: "fabric-achievements-view fabric-achievements-leaderboard",
      id: "fabric-achievements-panel-leaderboard",
      role: "tabpanel",
      "aria-labelledby": "fabric-achievements-tab-leaderboard",
    },
      h("div", { className: "fabric-achievements-view-intro" },
        h("p", { className: "fabric-achievements-eyebrow" }, "Personal mastery first"),
        h("h2", null, "Leaderboard"),
        h("p", null, intro),
      ),
      h("nav", { className: "fabric-achievements-subnav", "aria-label": "Leaderboard board" },
        BOARD_DEFS.map(function (item) {
          return h("button", {
            key: item.id, type: "button", "aria-current": board === item.id ? "page" : undefined,
            onClick: function () { props.onBoard(item.id); },
          }, item.label);
        })),
      props.loading && !model ? h(LoadingState) : null,
      props.error && !model ? h(ErrorPanel, { title: "Leaderboard could not load", message: props.error, onRetry: props.onRetry }) : null,
      model && model.skippedLocalProfiles > 0 ? h("p", { className: "fabric-achievements-inline-note", role: "status" },
        formatNumber(model.skippedLocalProfiles) + " local profile" + (model.skippedLocalProfiles === 1 ? " was" : "s were") + " skipped safely.") : null,
      model ? h(React.Fragment, null,
        records.length ? h("ol", { className: "fabric-achievements-profile-list", "aria-label": board === "friendly" ? "Friendly imported cards" : "Local mastery profiles" },
          records.map(function (record, index) {
            return h(ProfileRecord, {
              key: record.id,
              item: record,
              rank: board === "profiles" && model.kind === "v2" ? index + 1 : null,
              legacy: model.kind === "legacy" && board !== "friendly",
              pendingDelete: props.pendingDeleteId === record.id,
              busy: props.busy,
              onBeginDelete: board === "friendly" ? props.onBeginDelete : null,
              onCancelDelete: props.onCancelDelete,
              onDelete: board === "friendly" ? props.onDelete : null,
            });
          }))
          : h("div", { className: "fabric-achievements-quiet-state is-compact" },
              h("h3", null, board === "friendly" ? "No Friendly cards imported" : board === "profiles" ? "No other readable profiles" : "Your mastery record is not ready"),
              h("p", null, board === "friendly"
                ? "Share and import are optional. Your own Journey works without a leaderboard."
                : "Complete a Journey quest or initialize the profile to create this record."),
            ),
        board === "friendly" ? h("div", { className: "fabric-achievements-friendly-tools" },
          h(SharePanel), h(ImportPanel, { onImport: props.onImport })) : null,
      ) : null,
    );
  }

  function TrackingDisclosure(props) {
    const tracking = props.journey.tracking;
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [exportText, setExportText] = useState("");
    const sources = objectValue(tracking.sources) || {};
    const sourceRows = ["observed", "historical", "self_attested"].map(function (key) {
      return [key, countValue(sources[key])];
    });

    function exportActivity() {
      setExportText("");
      props.onExport().then(function (payload) {
        const text = JSON.stringify(payload, null, 2);
        try {
          if (typeof Blob === "function" && URL && typeof URL.createObjectURL === "function") {
            const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = "fabric-achievement-activity.json";
            anchor.click();
            URL.revokeObjectURL(url);
            return;
          }
        } catch (_) { /* show the bounded JSON inline instead */ }
        setExportText(text);
      }).catch(function () { /* Parent notice explains the export failure. */ });
    }

    return h("details", { className: "fabric-achievements-tracking" },
      h("summary", null,
        h("span", null, icon(tracking.enabled ? "CheckCircle2" : "Pause"),
          h("strong", null, "How progress is tracked"),
          h("small", null, props.journey.legacyMode ? "Legacy fallback" : tracking.enabled ? "On · local only" : "Paused")),
        icon("ChevronDown"),
      ),
      h("div", { className: "fabric-achievements-tracking-body" },
        h("div", { className: "fabric-achievements-tracking-copy" },
          h("h2", null, "Local activity metadata only"),
          h("p", null, "Fabric records closed capability events on this profile. It does not read prompts, replies, tool arguments or results, URLs, paths, generated content, cost, or tokens for achievements."),
          tracking.retentionDays ? h("p", null,
            "Raw activity rows are kept locally for up to " + formatNumber(tracking.retentionDays) + " days; earned capability records remain after raw rows expire.") : null,
          props.journey.legacyMode ? h("p", { className: "fabric-achievements-inline-note" },
            "The guided Journey API is unavailable. Legacy milestones remain readable; V2 controls are disabled until the local backend supports them.") : null,
        ),
        tracking.settingsInvalid || tracking.droppedEvents || props.journey.warnings.length
          ? h("div", { className: "fabric-achievements-tracking-warnings", role: "status" },
              tracking.settingsInvalid ? h("p", { className: "fabric-achievements-inline-note is-warning" },
                icon("AlertTriangle"), journeyWarningLabel("settings_invalid")) : null,
              tracking.droppedEvents ? h("p", { className: "fabric-achievements-inline-note is-warning" },
                icon("AlertTriangle"), formatNumber(tracking.droppedEvents) + " local activity signal" + (tracking.droppedEvents === 1 ? " was" : "s were") + " dropped safely.") : null,
              props.journey.warnings.map(function (warning) {
                if (warning === "settings_invalid" && tracking.settingsInvalid) return null;
                if (warning === "observer_events_dropped" && tracking.droppedEvents) return null;
                return h("p", { key: warning, className: "fabric-achievements-inline-note is-warning" },
                  icon("AlertTriangle"), journeyWarningLabel(warning));
              }),
            )
          : null,
        h("dl", { className: "fabric-achievements-source-counts" },
          sourceRows.map(function (row) {
            return h("div", { key: row[0] }, h("dt", null, titleCase(row[0])), h("dd", null, formatNumber(row[1])));
          })),
        h("div", { className: "fabric-achievements-settings" },
          h("div", null,
            h("strong", null, "Tracking"),
            h("span", null, tracking.enabled ? "New local events can advance quests." : "No new events are recorded or backfilled while paused."),
            h(Button, {
              type: "button", size: "sm", outlined: true,
              disabled: props.busy || props.journey.legacyMode,
              onClick: function () { props.onSettings({ tracking_enabled: !tracking.enabled }); },
            }, icon(tracking.enabled ? "Pause" : "Play"), tracking.enabled ? "Pause tracking" : "Resume tracking"),
          ),
          h("label", { className: "fabric-achievements-check-setting" },
            h("input", {
              type: "checkbox", checked: tracking.activeTimeEnabled,
              disabled: props.busy || props.journey.legacyMode,
              onChange: function (event) { props.onSettings({ active_time_enabled: event.target.checked }); },
            }),
            h("span", null, h("strong", null, "Active-time tracking"), h("small", null, "Count meaningful work intervals with local idle caps.")),
          ),
          h("div", { className: "fabric-achievements-setting-select" },
            h(Label, { htmlFor: "fabric-achievements-celebration" }, "Celebrations"),
            h(Select, Object.assign({
              id: "fabric-achievements-celebration", value: tracking.celebrationMode,
              disabled: props.busy || props.journey.legacyMode,
            }, selectChangeHandler(function (value) { props.onSettings({ celebration_mode: value }); })),
              h(SelectOption, { value: "standard" }, "Standard"),
              h(SelectOption, { value: "quiet" }, "Quiet"),
              h(SelectOption, { value: "off" }, "Off"),
            ),
          ),
        ),
        h("div", { className: "fabric-achievements-data-actions" },
          h(Button, { type: "button", size: "sm", outlined: true, disabled: props.busy || props.journey.legacyMode, onClick: exportActivity },
            icon("FileText"), "Export activity metadata"),
          confirmDelete
            ? h("div", { className: "fabric-achievements-delete-confirm", role: "group", "aria-label": "Confirm activity metadata deletion" },
                h("p", null, "Delete recorded activity metadata? Earned achievements and Legacy unlocks remain."),
                h(Button, { type: "button", size: "sm", disabled: props.busy, onClick: function () {
                  props.onDeleteActivity().then(function () { setConfirmDelete(false); })
                    .catch(function () { /* Parent notice explains the deletion failure. */ });
                } }, props.busy ? "Deleting…" : "Confirm delete activity"),
                h(Button, { type: "button", size: "sm", ghost: true, disabled: props.busy, onClick: function () { setConfirmDelete(false); } }, "Cancel"),
              )
            : h(Button, { type: "button", size: "sm", ghost: true, disabled: props.busy || props.journey.legacyMode, onClick: function () { setConfirmDelete(true); } },
                icon("X"), "Delete activity metadata"),
        ),
        exportText ? h("div", { className: "fabric-achievements-export-fallback" },
          h(Label, { htmlFor: "fabric-achievements-export-json" }, "Exported activity metadata"),
          h("textarea", { id: "fabric-achievements-export-json", readOnly: true, rows: 8, value: exportText }),
        ) : null,
        tracking.allowedFields.length || tracking.excludedFields.length ? h("details", { className: "fabric-achievements-field-contract" },
          h("summary", null, "Inspect the metadata contract"),
          tracking.allowedFields.length ? h("p", null, "Allowed: " + tracking.allowedFields.join(", ") + ".") : null,
          tracking.excludedFields.length ? h("p", null, "Never used: " + tracking.excludedFields.join(", ") + ".") : null,
        ) : null,
      ),
    );
  }

  function AchievementsPage(hostProps) {
    const hostNavigate = hostProps && typeof hostProps.navigate === "function" ? hostProps.navigate : null;
    const hostLocation = hostProps && hostProps.location ? hostProps.location : null;
    const routedLocation = hostNavigate && hostLocation ? hostLocation : null;
    const [routeTick, setRouteTick] = useState(0);
    const locationKey = routedLocation
      ? routedLocation.pathname + routedLocation.search + routedLocation.hash
      : String(routeTick);
    const route = useMemo(function () { return readRoute(routedLocation); }, [locationKey]);
    const [journey, setJourney] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [degraded, setDegraded] = useState("");
    const [notice, setNotice] = useState("");
    const [busy, setBusy] = useState(false);
    const [legacyLeaderboard, setLegacyLeaderboard] = useState(null);
    const [leaderboardLoading, setLeaderboardLoading] = useState(false);
    const [leaderboardError, setLeaderboardError] = useState("");
    const [pendingDeleteId, setPendingDeleteId] = useState("");
    const [attestPendingId, setAttestPendingId] = useState("");
    const viewRefs = useRef([]);
    const requestRef = useRef(0);
    const boardRequestRef = useRef(0);

    const loadJourney = useCallback(function () {
      const requestId = ++requestRef.current;
      setLoading(true);
      setError("");
      setDegraded("");
      return SDK.fetchJSON(API + "/journey").then(function (payload) {
        if (requestId !== requestRef.current) return null;
        const model = normalizeJourney(payload);
        setJourney(model);
        setNotice(celebrationNotice(model, ""));
        return model;
      }).catch(function (journeyError) {
        return SDK.fetchJSON(API + "/summary").then(function (payload) {
          if (requestId !== requestRef.current) return null;
          const model = journeyFromLegacy(payload);
          setJourney(model);
          setDegraded("Guided Journey data is unavailable. Showing preserved Legacy progress and a safe starter fallback.");
          return model;
        }).catch(function () {
          if (requestId === requestRef.current) setError(parseApiErrorMessage(journeyError));
          throw journeyError;
        });
      }).finally(function () {
        if (requestId === requestRef.current) setLoading(false);
      });
    }, []);

    const loadLegacyLeaderboard = useCallback(function () {
      const requestId = ++boardRequestRef.current;
      setLeaderboardLoading(true);
      setLeaderboardError("");
      return SDK.fetchJSON(API + "/leaderboard").then(function (payload) {
        if (requestId !== boardRequestRef.current) return null;
        const model = normalizeLegacyLeaderboard(payload);
        setLegacyLeaderboard(model);
        return model;
      }).catch(function (reason) {
        if (requestId === boardRequestRef.current) setLeaderboardError(parseApiErrorMessage(reason));
        throw reason;
      }).finally(function () {
        if (requestId === boardRequestRef.current) setLeaderboardLoading(false);
      });
    }, []);

    useEffect(function () {
      loadJourney().catch(function () { /* error renders in page */ });
      return function () {
        requestRef.current += 1;
        boardRequestRef.current += 1;
      };
    }, [loadJourney]);

    useEffect(function () {
      if (routedLocation) return undefined;
      function update() { setRouteTick(function (value) { return value + 1; }); }
      window.addEventListener("popstate", update);
      return function () { window.removeEventListener("popstate", update); };
    }, [routedLocation]);

    useEffect(function () {
      if (!route.migrate) return;
      writeRoute({ view: route.view }, "replace", hostNavigate, routedLocation);
    }, [route.migrate, route.view, locationKey]);

    useEffect(function () {
      if (route.view !== "leaderboard" || !journey) return;
      if (journey.leaderboard || legacyLeaderboard || leaderboardLoading || leaderboardError) return;
      loadLegacyLeaderboard().catch(function () { /* error renders in board */ });
    }, [route.view, journey, legacyLeaderboard, leaderboardLoading, leaderboardError, loadLegacyLeaderboard]);

    useEffect(function () {
      if (!route.focus || !journey) return;
      const target = document.getElementById("fabric-quest-" + safeId(route.focus));
      if (!target) return;
      target.focus({ preventScroll: true });
      const reduceMotion = typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      try { target.scrollIntoView({ block: "center", behavior: reduceMotion ? "auto" : "smooth" }); }
      catch (_) { target.scrollIntoView(); }
    }, [route.focus, journey, route.view, route.path]);

    function changeView(view) {
      if (!VIEW_SET.has(view)) return;
      writeRoute({ view: view }, "push", hostNavigate, routedLocation);
    }

    function moveView(event, index) {
      let next = index;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % VIEWS.length;
      else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (index - 1 + VIEWS.length) % VIEWS.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = VIEWS.length - 1;
      else return;
      event.preventDefault();
      changeView(VIEWS[next]);
      if (viewRefs.current[next]) viewRefs.current[next].focus();
    }

    function changePath(pathId) {
      writeRoute({ view: "paths", path: pathId }, route.view === "paths" ? "replace" : "push", hostNavigate, routedLocation);
    }

    function handleAction(quest) {
      const action = quest && quest.action;
      if (!action) return;
      if (action.kind === "chat") {
        hostNavigate ? hostNavigate(chatRoute(action.draft)) : window.location.assign(chatRoute(action.draft));
      } else if (action.kind === "route" && action.route) {
        hostNavigate ? hostNavigate(action.route) : window.location.assign(action.route);
      }
    }

    function updateJourneyFromPayload(payload, localPatch) {
      try {
        const model = normalizeJourney(payload);
        setJourney(model);
        return model;
      } catch (_) {
        setJourney(function (current) { return localPatch(current); });
        return null;
      }
    }

    function patchSettings(patch) {
      if (!journey || journey.legacyMode || busy) return Promise.resolve(null);
      setBusy(true);
      setNotice("");
      return SDK.fetchJSON(API + "/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }).then(function (payload) {
        updateJourneyFromPayload(payload, function (current) {
          if (!current) return current;
          const next = Object.assign({}, current, {
            onboarding: Object.assign({}, current.onboarding),
            tracking: Object.assign({}, current.tracking),
          });
          if (Object.prototype.hasOwnProperty.call(patch, "preferred_outcome")) {
            next.onboarding.selectedOutcome = patch.preferred_outcome;
          }
          if (Object.prototype.hasOwnProperty.call(patch, "tracking_enabled")) {
            next.tracking.enabled = patch.tracking_enabled === true;
            next.tracking.state = next.tracking.enabled ? "active" : "paused";
          }
          if (Object.prototype.hasOwnProperty.call(patch, "active_time_enabled")) {
            next.tracking.activeTimeEnabled = patch.active_time_enabled === true;
          }
          if (Object.prototype.hasOwnProperty.call(patch, "celebration_mode")) {
            next.tracking.celebrationMode = patch.celebration_mode;
          }
          return next;
        });
        setNotice("Journey preferences saved locally.");
        return payload;
      }).catch(function (reason) {
        setNotice("Could not save Journey preferences: " + parseApiErrorMessage(reason));
        throw reason;
      }).finally(function () { setBusy(false); });
    }

    function snoozeQuest(quest) {
      if (!quest || !journey || journey.legacyMode || busy) return;
      setBusy(true);
      setNotice("");
      SDK.fetchJSON(API + "/quests/" + encodeURIComponent(quest.id) + "/snooze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days: 7 }),
      }).then(function (payload) {
        const model = updateJourneyFromPayload(payload, function (current) {
          if (!current) return current;
          const next = Object.assign({}, current, { today: Object.assign({}, current.today) });
          if (next.today.primary && next.today.primary.id === quest.id) {
            next.today.primary = Object.assign({}, next.today.primary, { status: "snoozed" });
          }
          return next;
        });
        const unlocked = celebrationNotice(model, "");
        setNotice(quest.title + " snoozed for seven days." + (unlocked ? " " + unlocked : ""));
      }).catch(function (reason) {
        setNotice("Snooze is unavailable: " + parseApiErrorMessage(reason));
      }).finally(function () { setBusy(false); });
    }

    function attestQuest(quest) {
      if (!quest || !journey || journey.legacyMode || quest.id !== LINKEDIN_QUEST_ID || busy) return;
      setBusy(true);
      setNotice("");
      SDK.fetchJSON(API + "/quests/" + encodeURIComponent(quest.id) + "/attest", {
        method: "POST",
      }).then(function (payload) {
        setAttestPendingId("");
        setNotice("Published marked as self-attested. This earns 0 rank XP and is not treated as verified.");
        try {
          setJourney(normalizeJourney(payload));
          return null;
        } catch (_) {
          return loadJourney();
        }
      }).catch(function (reason) {
        setNotice("Self-attestation is unavailable: " + parseApiErrorMessage(reason));
      }).finally(function () { setBusy(false); });
    }

    function rerollChallenge(kind) {
      if (!journey || journey.legacyMode || busy || (kind !== "daily" && kind !== "weekly")) return;
      setBusy(true);
      setNotice("");
      SDK.fetchJSON(API + "/challenges/" + kind + "/reroll", {
        method: "POST",
      }).then(function (payload) {
        const model = normalizeJourney(payload);
        setJourney(model);
        const swapped = kind === "daily" ? "Daily quest swapped." : "Weekly expedition swapped.";
        const unlocked = celebrationNotice(model, "");
        setNotice(swapped + (unlocked ? " " + unlocked : ""));
      }).catch(function (reason) {
        setNotice("Reroll is unavailable: " + parseApiErrorMessage(reason));
      }).finally(function () { setBusy(false); });
    }

    function refreshJourney() {
      if (!journey || busy) return;
      setBusy(true);
      setNotice("");
      const endpoint = journey.legacyMode ? "/refresh" : "/journey/refresh";
      SDK.fetchJSON(API + endpoint, { method: "POST" }).then(function (payload) {
        const model = journey.legacyMode ? journeyFromLegacy(payload) : normalizeJourney(payload);
        setJourney(model);
        setNotice(celebrationNotice(model, "Journey refreshed from local activity metadata."));
      }).catch(function (reason) {
        setNotice("Refresh failed: " + parseApiErrorMessage(reason));
      }).finally(function () { setBusy(false); });
    }

    function importCard(raw) {
      return SDK.fetchJSON(API + "/leaderboard/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: raw,
      }).then(function (payload) {
        setNotice("Friendly card imported as self-reported.");
        return Promise.all([
          loadJourney().catch(function () { return null; }),
          loadLegacyLeaderboard().catch(function () { return null; }),
        ]).then(function () { return payload; });
      });
    }

    function deleteFriendly(record) {
      if (!record || !record.cardId || busy) return Promise.resolve(null);
      setBusy(true);
      return SDK.fetchJSON(API + "/leaderboard/" + encodeURIComponent(record.cardId), {
        method: "DELETE",
      }).then(function (payload) {
        setPendingDeleteId("");
        setNotice("Friendly card removed from this device.");
        return Promise.all([
          loadJourney().catch(function () { return null; }),
          loadLegacyLeaderboard().catch(function () { return null; }),
        ]).then(function () { return payload; });
      }).catch(function (reason) {
        setNotice("Could not remove Friendly card: " + parseApiErrorMessage(reason));
        throw reason;
      }).finally(function () { setBusy(false); });
    }

    function exportActivity() {
      if (!journey || journey.legacyMode) return Promise.reject(new Error("Activity export needs the guided Journey backend."));
      setBusy(true);
      return SDK.fetchJSON(API + "/activity/export").then(function (payload) {
        setNotice("Activity metadata exported locally.");
        return payload;
      }).catch(function (reason) {
        setNotice("Activity export is unavailable: " + parseApiErrorMessage(reason));
        throw reason;
      }).finally(function () { setBusy(false); });
    }

    function deleteActivity() {
      if (!journey || journey.legacyMode) return Promise.reject(new Error("Activity deletion needs the guided Journey backend."));
      setBusy(true);
      return SDK.fetchJSON(API + "/activity", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      }).then(function (payload) {
        setNotice("Activity metadata deleted. Observed achievements and Legacy progress were preserved; self-attested activity was cleared.");
        return loadJourney().then(function () { return payload; });
      }).catch(function (reason) {
        setNotice("Could not delete activity metadata: " + parseApiErrorMessage(reason));
        throw reason;
      }).finally(function () { setBusy(false); });
    }

    const leaderboardModel = journey && journey.leaderboard ? journey.leaderboard : legacyLeaderboard;

    return h(ErrorBoundary, null,
      h("div", { className: "fabric-achievements" },
        h("div", { className: "fabric-achievements-page-intro" },
          h("div", null,
            h("p", { className: "fabric-achievements-eyebrow" }, "Learn by doing"),
            h("h2", null, "Fabric Journey"),
            h("p", null, "One useful next quest, clear capability paths, and a private record of what you have learned."),
          ),
          h("div", { className: "fabric-achievements-page-actions" },
            journey ? h("span", null, icon("Clock3", { size: 14 }), "Updated " + formatDate(journey.generatedAt)) : null,
            h(Button, { type: "button", size: "sm", outlined: true, disabled: busy || loading, onClick: refreshJourney },
              icon("RotateCcw"), busy ? "Working…" : "Refresh"),
          ),
        ),
        h("nav", { className: "fabric-achievements-tabs", "aria-label": "Achievement views" },
          h("div", { role: "tablist", "aria-label": "Achievement views" },
            VIEW_DEFS.map(function (view, index) {
              const active = route.view === view.id;
              return h("button", {
                key: view.id,
                ref: function (node) { viewRefs.current[index] = node; },
                id: "fabric-achievements-tab-" + view.id,
                type: "button",
                role: "tab",
                tabIndex: active ? 0 : -1,
                "aria-selected": active,
                "aria-controls": "fabric-achievements-panel-" + view.id,
                onClick: function () { changeView(view.id); },
                onKeyDown: function (event) { moveView(event, index); },
              }, icon(view.icon), view.label);
            }))),
        notice ? h("p", {
          className: notice.indexOf("failed") >= 0 || notice.indexOf("Could not") >= 0 ? "fabric-achievements-notice is-error" : "fabric-achievements-notice",
          role: "status",
          "aria-live": "polite",
        }, icon("CheckCircle2"), notice) : null,
        degraded ? h("p", { className: "fabric-achievements-inline-note", role: "status" }, degraded) : null,
        loading && !journey ? h(LoadingState) : null,
        error && !journey ? h(ErrorPanel, { title: "Your Fabric Journey could not load", message: error, onRetry: function () { loadJourney().catch(function () {}); } }) : null,
        journey ? h(React.Fragment, null,
          route.view === "today" ? h(TodayView, {
            journey: journey,
            onOutcome: function (id) { patchSettings({ preferred_outcome: id }).catch(function () {}); },
            onAction: handleAction,
            onSnooze: journey.legacyMode ? null : snoozeQuest,
            onReroll: journey.legacyMode ? null : rerollChallenge,
            onExplore: function () { changeView("paths"); },
            onPath: changePath,
            busy: busy,
          }) : null,
          route.view === "paths" ? h(PathsView, {
            journey: journey,
            selectedPath: route.path,
            onPath: changePath,
            onAction: handleAction,
            busy: busy,
            attestPendingId: attestPendingId,
            onBeginAttest: setAttestPendingId,
            onCancelAttest: function () { setAttestPendingId(""); },
            onAttest: attestQuest,
          }) : null,
          route.view === "collection" ? h(CollectionView, {
            journey: journey,
            status: route.status,
            onStatus: function (status) { writeRoute({ view: "collection", status: status }, "replace", hostNavigate, routedLocation); },
          }) : null,
          route.view === "leaderboard" ? h(LeaderboardView, {
            board: route.board,
            model: leaderboardModel,
            loading: leaderboardLoading,
            error: leaderboardError,
            onRetry: function () { loadLegacyLeaderboard().catch(function () {}); },
            onBoard: function (board) { writeRoute({ view: "leaderboard", board: board }, "replace", hostNavigate, routedLocation); },
            onImport: importCard,
            pendingDeleteId: pendingDeleteId,
            onBeginDelete: setPendingDeleteId,
            onCancelDelete: function () { setPendingDeleteId(""); },
            onDelete: deleteFriendly,
            busy: busy,
          }) : null,
          h(TrackingDisclosure, {
            journey: journey,
            busy: busy,
            onSettings: function (patch) { patchSettings(patch).catch(function () {}); },
            onExport: exportActivity,
            onDeleteActivity: deleteActivity,
          }),
        ) : null,
      ),
    );
  }

  registry.register("achievements", AchievementsPage);
})();
