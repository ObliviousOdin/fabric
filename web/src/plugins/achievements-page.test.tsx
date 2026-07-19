// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import achievementBundle from "../../../plugins/achievements/dashboard/dist/index.js?raw";
import { PluginPage } from "./PluginPage";
import { exposePluginSDK } from "./registry";

vi.mock("@/i18n", () => ({
  useI18n: () => ({
    t: {
      common: {
        loading: "Loading",
        pluginLoadFailed: "Load failed",
        pluginNotRegistered: "Not registered",
      },
    },
  }),
}));

const reactActEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

interface FetchInit {
  method?: string;
  body?: BodyInit | null;
}

interface FixtureOptions {
  firstRun?: boolean;
  starterCompleted?: boolean;
  primaryId?: string;
  includeProjectedLeaderboard?: boolean;
  activeTimeEnabled?: boolean;
  celebrationMode?: "standard" | "quiet" | "off";
  newlyEarned?: boolean;
  selectedOutcome?: string | null;
}

function quest(
  id: string,
  title: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    id,
    path_id: "conversation",
    capability: "conversation",
    title,
    description: `Learn ${title.toLowerCase()} through a real outcome.`,
    why: "This is the most useful next capability for this profile.",
    xp: 50,
    estimate_minutes: 10,
    status: "available",
    confidence: "observed",
    progress: { current: 0, target: 1, label: "0 of 1" },
    action: {
      kind: "chat",
      label: "Start in Chat",
      draft: `Help me complete ${title.toLowerCase()}.`,
    },
    ...overrides,
  };
}

function journeyFixture(options: FixtureOptions = {}) {
  const firstRun = options.firstRun ?? false;
  const starterCompleted = options.starterCompleted ?? !firstRun;
  const primary = quest(
    options.primaryId ?? "conversation.follow_through",
    "Finish a tool-assisted outcome",
    { xp: 0, momentum: 10, snoozeable: true, reroll_available: true },
  );
  const linkedin = quest(
    "content.linkedin_launch",
    "Publish a useful LinkedIn post",
    {
      path_id: "create",
      capability: "content_publishing",
      xp: 500,
      confidence: "observed",
      rank_eligible: true,
      action: {
        kind: "chat",
        label: "Draft in Chat",
        draft: "Draft a thoughtful LinkedIn launch post for me to review.",
      },
    },
  );
  const leaderboard = options.includeProjectedLeaderboard
    ? {
        you: [
          {
            profile: "default",
            display_name: "Current profile",
            is_current_profile: true,
            xp: 620,
            level: { id: "builder", label: "Builder" },
            earned_count: 7,
            breadth: 4,
            momentum: 12,
          },
        ],
        profiles: [
          {
            profile: "default",
            display_name: "Current duplicate",
            is_current_profile: true,
            xp: 620,
          },
          {
            profile: "ada",
            display_name: "Ada profile",
            xp: 900,
            level: { id: "orchestrator", label: "Orchestrator" },
            earned_count: 11,
            breadth: 6,
            momentum: 18,
          },
        ],
        friendly: [
          {
            origin: "self_reported_import",
            confidence: "self_attested",
            card: {
              card_id: "11111111-1111-4111-8111-111111111111",
              display_name: "Friendly Pal",
              score: 321,
              earned_count: 4,
              generated_at: "2026-07-19T12:00:00Z",
              achievement_ids: [],
              category_totals: {},
            },
          },
        ],
      }
    : undefined;

  return {
    schema_version: 2,
    generated_at: "2026-07-19T12:00:00Z",
    profile: "default",
    onboarding: {
      is_first_run: firstRun,
      selected_outcome:
        options.selectedOutcome !== undefined
          ? options.selectedOutcome
          : firstRun
            ? null
            : "finish_faster",
      outcomes: [
        {
          id: "finish_faster",
          label: "Finish work faster",
          description: "Complete a real tool-assisted outcome.",
          preferred_paths: ["conversation", "computer_use", "deep_work"],
        },
        {
          id: "create_content",
          label: "Create content",
          description: "Make and prepare useful content.",
          preferred_paths: ["create", "skills", "conversation"],
        },
      ],
    },
    mastery: {
      xp: 620,
      level: { id: "builder", label: "Builder" },
      next_level: {
        id: "orchestrator",
        label: "Orchestrator",
        xp_required: 1000,
        requirements: [
          {
            id: "breadth",
            label: "Build breadth",
            current: 4,
            target: 6,
            met: false,
          },
        ],
      },
      breadth: { current: 4, target: 6, label: "4 of 6 capability paths" },
      earned_count: 7,
    },
    starter: {
      id: "starter",
      status: starterCompleted ? "completed" : "active",
      step_index: starterCompleted ? 3 : 0,
      total_steps: 3,
      steps: [
        quest("conversation.first_thread", "Start one useful chat", {
          status: starterCompleted ? "completed" : "available",
        }),
        quest("starter.tool_assist", "Complete a tool-assisted action", {
          status: starterCompleted ? "completed" : "unavailable",
          action: { kind: "none" },
        }),
        quest("agents.first_delegate", "Delegate one bounded task", {
          path_id: "agent_crew",
          status: starterCompleted ? "completed" : "unavailable",
          action: { kind: "none" },
        }),
      ],
      action: {
        kind: "chat",
        label: "Start in Chat",
        draft: "Help me complete one useful outcome today.",
      },
    },
    today: {
      primary,
      optional: [
        linkedin,
        quest("agents.first_delegate", "Delegate one bounded task", {
          path_id: "agent_crew",
        }),
        quest("images.first_generation", "Generate a useful image", {
          path_id: "create",
        }),
      ],
      weekly: quest("weekly.cross_capability", "Cross two capabilities", {
        path_id: "weekly",
        xp: 0,
        momentum: 60,
        reroll_available: true,
      }),
      reflection: {
        active_minutes: 95,
        meaningful_outcomes: 2,
        active_days_7: 4,
        rank_eligible: false,
      },
      momentum: { points: 12, season_id: "2026-W29", next_checkpoint: 20 },
      recent_wins: [
        linkedin,
        quest("skills.first_use", "Use a Fabric skill", {
          status: "completed",
          earned: true,
        }),
      ],
      active_paths: [],
    },
    paths: [
      {
        id: "conversation",
        title: "Conversation craft",
        description: "Turn chats into finished outcomes.",
        status: "active",
        progress: { current: 1, target: 3, label: "1 of 3" },
        steps: [primary],
        next_achievement_id: primary.id,
      },
      {
        id: "create",
        title: "Create",
        description: "Research, make, and prepare content.",
        status: "available",
        progress: { current: 0, target: 2, label: "0 of 2" },
        steps: [],
      },
      {
        id: "skills",
        title: "Skills",
        description: "Use, combine, and improve Fabric skills.",
        status: "available",
        progress: { current: 0, target: 1, label: "0 of 1" },
        steps: [],
      },
    ],
    collection: {
      earned: [],
      active: [primary],
      discover: [],
      legacy: [],
    },
    tracking: {
      enabled: true,
      active_time_enabled: options.activeTimeEnabled ?? true,
      celebration_mode: options.celebrationMode ?? "standard",
      state: "active",
      raw_event_retention_days: 90,
      dropped_events: 0,
      settings_invalid: false,
      sources: { observed: 8, historical: 2, self_attested: 1 },
      allowed_fields: ["event_type", "occurred_at", "capability"],
      excluded_fields: ["prompt", "response", "tool_arguments"],
    },
    leaderboard,
    newly_earned: options.newlyEarned
      ? [
          quest("skills.first_use", "Use a Fabric skill", {
            status: "completed",
            earned: true,
          }),
        ]
      : [],
    warnings: [],
  };
}

function legacySummaryFixture() {
  return {
    schema_version: 1,
    score: 75,
    earned_count: 1,
    generated_at: "2026-07-19T12:00:00Z",
    tracks: [
      {
        id: "sessions",
        value: 2,
        milestones: [
          {
            id: "legacy.sessions.1",
            title: "Legacy regular",
            description: "Preserved original milestone.",
            points: 75,
            threshold: 1,
            earned: true,
            earned_at: "2026-07-18T12:00:00Z",
          },
        ],
      },
    ],
    warnings: [],
  };
}

function buttonWithText(
  container: ParentNode,
  text: string,
): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.trim() === text,
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`button not found: ${text}`);
  }
  return button;
}

function buttonContaining(
  container: ParentNode,
  text: string,
): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.includes(text),
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`button not found containing: ${text}`);
  }
  return button;
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-route>
      {`${location.pathname}${location.search}${location.hash}`}
    </output>
  );
}

function TestShell({ initialEntry }: { initialEntry: string }) {
  return (
    <MemoryRouter initialEntries={[initialEntry]}>
      <main>
        <h1>Achievements</h1>
        <LocationProbe />
        <Routes>
          <Route
            path="/workspace/achievements"
            element={<PluginPage name="achievements" />}
          />
          <Route
            path="/workspace/chat"
            element={<div data-chat-destination>Chat destination</div>}
          />
        </Routes>
      </main>
    </MemoryRouter>
  );
}

async function settle(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("Fabric Journey achievements page", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    exposePluginSDK();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
  });

  function installBundle(fetchJSON: ReturnType<typeof vi.fn>) {
    const sdk = window.__FABRIC_PLUGIN_SDK__ as unknown as {
      fetchJSON: typeof fetchJSON;
    };
    sdk.fetchJSON = fetchJSON;
    window.eval(achievementBundle);
  }

  it("uses the host page shell and gives a new profile an outcome-first starter", async () => {
    const fetchJSON = vi.fn(
      (url: string, _init?: FetchInit): Promise<unknown> => {
        if (url.endsWith("/journey"))
          return Promise.resolve(journeyFixture({ firstRun: true }));
        if (url.endsWith("/settings")) return Promise.resolve({ ok: true });
        return Promise.reject(new Error(`unexpected request: ${url}`));
      },
    );
    installBundle(fetchJSON);

    await act(async () => {
      root.render(
        <TestShell initialEntry="/workspace/achievements?keep=yes#journey" />,
      );
    });
    await settle();

    expect(container.querySelectorAll("main")).toHaveLength(1);
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    expect(container.textContent).toContain("Learn Fabric by doing");
    expect(container.textContent).toContain(
      "Three steps to your first Fabric workflow",
    );
    expect(container.textContent).not.toContain("0 mastery XP");
    expect(container.textContent).not.toContain("Today's rhythm");

    await act(async () =>
      buttonContaining(container, "Create content").click(),
    );
    await settle();
    const settingsCall = fetchJSON.mock.calls.find(([url]) =>
      String(url).endsWith("/settings"),
    );
    expect(settingsCall?.[1]).toMatchObject({ method: "PATCH" });
    expect(JSON.parse(String((settingsCall?.[1] as FetchInit).body))).toEqual({
      preferred_outcome: "create_content",
    });

    await act(async () => buttonWithText(container, "Start in Chat").click());
    const route = container.querySelector("[data-route]")?.textContent ?? "";
    expect(route).toMatch(/^\/workspace\/chat\?fresh=[^&]+&draft=/);
    expect(new URLSearchParams(route.split("?")[1]).get("draft")).toBe(
      "Help me complete one useful outcome today.",
    );
    expect(container.querySelector("[data-chat-destination]")).not.toBeNull();
  });

  it("keeps an outcome-selected profile in onboarding until the starter is complete", async () => {
    const fetchJSON = vi.fn(() =>
      Promise.resolve(
        journeyFixture({
          firstRun: false,
          starterCompleted: false,
          selectedOutcome: "create_content",
        }),
      ),
    );
    installBundle(fetchJSON);

    await act(async () => {
      root.render(<TestShell initialEntry="/workspace/achievements" />);
    });
    await settle();

    expect(container.textContent).toContain("Learn Fabric by doing");
    expect(container.textContent).not.toContain("Snooze 7 days");
    const recommendations = Array.from(
      container.querySelectorAll(".fabric-achievements-recommended button"),
    ).map((item) => item.textContent ?? "");
    expect(recommendations).toHaveLength(3);
    expect(recommendations[0]).toContain("Create");
    expect(recommendations[1]).toContain("Skills");
    expect(recommendations[2]).toContain("Conversation craft");
  });

  it("keeps Today bounded, excludes self-attested publishing, and shows private time", async () => {
    const fetchJSON = vi.fn((_url: string) =>
      Promise.resolve(journeyFixture()),
    );
    installBundle(fetchJSON);

    await act(async () => {
      root.render(
        <TestShell initialEntry="/workspace/achievements?keep=yes#today" />,
      );
    });
    await settle();

    expect(container.textContent).toContain("1h 35m");
    expect(container.textContent).toContain("2 meaningful outcomes today");
    expect(container.textContent).toContain("Private, non-XP");
    expect(container.textContent).toContain("10 Momentum");
    expect(container.textContent).toContain("60 Momentum");
    expect(
      container.querySelector(".fabric-achievements-primary-quest")
        ?.textContent,
    ).not.toContain("0 XP");
    expect(container.textContent).toContain("kept locally for up to 90 days");
    expect(container.textContent).not.toContain(
      "Publish a useful LinkedIn post",
    );
    expect(container.textContent).toContain("Delegate one bounded task");
    expect(container.textContent).toContain("Generate a useful image");
    expect(
      container.querySelectorAll('[role="progressbar"]').length,
    ).toBeGreaterThan(0);

    await act(async () => buttonWithText(container, "Paths").click());
    expect(container.querySelector("[data-route]")?.textContent).toBe(
      "/workspace/achievements?keep=yes&view=paths#today",
    );
  });

  it("hides active-time reflection immediately when the local setting is turned off", async () => {
    const fetchJSON = vi.fn(
      (url: string, init?: FetchInit): Promise<unknown> => {
        if (url.endsWith("/journey")) return Promise.resolve(journeyFixture());
        if (url.endsWith("/settings") && init?.method === "PATCH") {
          return Promise.resolve({ ok: true });
        }
        return Promise.reject(new Error(`unexpected request: ${url}`));
      },
    );
    installBundle(fetchJSON);

    await act(async () => {
      root.render(<TestShell initialEntry="/workspace/achievements" />);
    });
    await settle();
    expect(container.textContent).toContain("Today's rhythm");

    const activeTime = container.querySelector(
      ".fabric-achievements-check-setting input",
    );
    if (!(activeTime instanceof HTMLInputElement)) {
      throw new Error("active-time setting not found");
    }
    await act(async () => activeTime.click());
    await settle();

    expect(container.textContent).not.toContain("Today's rhythm");
    const settingsCall = fetchJSON.mock.calls.find(([url]) =>
      String(url).endsWith("/settings"),
    );
    expect(JSON.parse(String((settingsCall?.[1] as FetchInit).body))).toEqual({
      active_time_enabled: false,
    });
  });

  it("shows the snoozed quest replacement and exposes each free reroll", async () => {
    const initial = journeyFixture({ primaryId: "daily.one" });
    const replacement = journeyFixture({ primaryId: "daily.two" });
    replacement.today.primary.title = "Use a different capability";
    const rerolled = journeyFixture({ primaryId: "daily.three" });
    rerolled.today.primary.title = "Try a third capability";
    const fetchJSON = vi.fn(
      (url: string, init?: FetchInit): Promise<unknown> => {
        if (url.endsWith("/journey")) return Promise.resolve(initial);
        if (
          url.endsWith("/quests/daily.one/snooze") &&
          init?.method === "POST"
        ) {
          return Promise.resolve(replacement);
        }
        if (
          url.endsWith("/challenges/daily/reroll") &&
          init?.method === "POST"
        ) {
          return Promise.resolve(rerolled);
        }
        return Promise.reject(new Error(`unexpected request: ${url}`));
      },
    );
    installBundle(fetchJSON);

    await act(async () => {
      root.render(<TestShell initialEntry="/workspace/achievements" />);
    });
    await settle();

    await act(async () => buttonWithText(container, "Snooze 7 days").click());
    await settle();
    expect(
      container.querySelector(".fabric-achievements-primary-quest h2")
        ?.textContent,
    ).toBe("Use a different capability");

    await act(async () => buttonWithText(container, "Swap quest").click());
    await settle();
    expect(container.textContent).toContain("Try a third capability");
    expect(container.textContent).toContain("Swap expedition");
  });

  it.each([
    ["standard", "Unlocked: Use a Fabric skill.", true],
    ["quiet", "1 new unlock.", false],
    ["off", null, false],
  ] as const)(
    "honors %s unlock celebrations on initial load",
    async (mode, expected, namesShown) => {
      const fetchJSON = vi.fn(() =>
        Promise.resolve(
          journeyFixture({ celebrationMode: mode, newlyEarned: true }),
        ),
      );
      installBundle(fetchJSON);

      await act(async () => {
        root.render(<TestShell initialEntry="/workspace/achievements" />);
      });
      await settle();

      const notice = container.querySelector(".fabric-achievements-notice");
      if (expected) expect(notice?.textContent).toContain(expected);
      else expect(notice).toBeNull();
      if (!namesShown && notice) {
        expect(notice.textContent).not.toContain("Use a Fabric skill");
      }
    },
  );

  it("keeps LinkedIn guided and explicitly self-attested inside Create", async () => {
    const fetchJSON = vi.fn(
      (url: string, init?: FetchInit): Promise<unknown> => {
        if (url.endsWith("/journey")) return Promise.resolve(journeyFixture());
        if (
          url.endsWith("/quests/content.linkedin_launch/attest") &&
          init?.method === "POST"
        ) {
          return Promise.resolve({ ok: true });
        }
        return Promise.reject(new Error(`unexpected request: ${url}`));
      },
    );
    installBundle(fetchJSON);

    await act(async () => {
      root.render(
        <TestShell initialEntry="/workspace/achievements?view=paths&path=create" />,
      );
    });
    await settle();

    expect(container.textContent).toContain("Publish a useful LinkedIn post");
    expect(container.textContent).toContain("Self-attested");
    expect(container.textContent).toContain("0 rank XP");
    expect(container.textContent).toContain("cannot be verified locally");

    expect(
      fetchJSON.mock.calls.some(([url]) => String(url).includes("/attest")),
    ).toBe(false);
    await act(async () =>
      buttonWithText(container, "Mark as published").click(),
    );
    expect(container.textContent).toContain("Confirm self-attested publish");
    await act(async () =>
      buttonWithText(container, "Confirm self-attested publish").click(),
    );
    await settle();
    const attestCall = fetchJSON.mock.calls.find(([url]) =>
      String(url).endsWith("/quests/content.linkedin_launch/attest"),
    );
    expect(attestCall?.[1]).toMatchObject({ method: "POST" });
    expect((attestCall?.[1] as FetchInit).body).toBeUndefined();

    await act(async () => buttonWithText(container, "Draft in Chat").click());
    expect(container.querySelector("[data-route]")?.textContent).toMatch(
      /^\/workspace\/chat\?fresh=[^&]+&draft=/,
    );
  });

  it("migrates legacy routes and keeps observed profiles separate from Friendly cards", async () => {
    const fetchJSON = vi.fn((_url: string) =>
      Promise.resolve(journeyFixture({ includeProjectedLeaderboard: true })),
    );
    installBundle(fetchJSON);

    await act(async () => {
      root.render(
        <TestShell initialEntry="/workspace/achievements?tab=leaderboard&keep=yes#rank" />,
      );
    });
    await settle();

    expect(container.querySelector("[data-route]")?.textContent).toBe(
      "/workspace/achievements?keep=yes&view=leaderboard#rank",
    );
    expect(container.textContent).toContain("Current profile");
    expect(container.textContent).not.toContain("Current duplicate");

    await act(async () => buttonWithText(container, "Profiles").click());
    expect(container.textContent).toContain("Ada profile");
    expect(container.textContent).not.toContain("Current duplicate");

    await act(async () => buttonWithText(container, "Friendly").click());
    expect(container.textContent).toContain("Friendly Pal");
    expect(container.textContent).toContain("Self-reported Legacy score 321");
    expect(container.textContent).toContain(
      "never mixed with verified local mastery",
    );
    expect(
      fetchJSON.mock.calls.some(([url]) =>
        String(url).endsWith("/leaderboard"),
      ),
    ).toBe(false);
  });

  it("degrades to clearly labeled Legacy progress when Journey V2 is unavailable", async () => {
    const fetchJSON = vi.fn((url: string): Promise<unknown> => {
      if (url.endsWith("/journey"))
        return Promise.reject(new Error("404: missing"));
      if (url.endsWith("/summary"))
        return Promise.resolve(legacySummaryFixture());
      return Promise.reject(new Error(`unexpected request: ${url}`));
    });
    installBundle(fetchJSON);

    await act(async () => {
      root.render(
        <TestShell initialEntry="/workspace/achievements?view=collection&status=legacy" />,
      );
    });
    await settle();

    expect(container.textContent).toContain(
      "Showing preserved Legacy progress",
    );
    expect(container.textContent).toContain("Legacy regular");
    expect(container.textContent).toContain(
      "does not drive V2 recommendations",
    );
    expect(buttonWithText(container, "Pause tracking").disabled).toBe(true);

    await act(async () => buttonWithText(container, "Today").click());
    expect(container.textContent).not.toContain("Snooze 7 days");
    await act(async () => buttonWithText(container, "Paths").click());
    expect(container.textContent).not.toContain(
      "Publish a useful LinkedIn post",
    );
    expect(container.textContent).not.toContain("Mark as published");
  });

  it("requires inline confirmation before deleting private activity metadata", async () => {
    const fetchJSON = vi.fn(
      (url: string, init?: FetchInit): Promise<unknown> => {
        if (url.endsWith("/journey")) return Promise.resolve(journeyFixture());
        if (url.endsWith("/settings") && init?.method === "PATCH") {
          return Promise.resolve({ ok: true });
        }
        if (url.endsWith("/activity/export"))
          return Promise.resolve({ events: [] });
        if (url.endsWith("/activity") && init?.method === "DELETE") {
          return Promise.resolve({ ok: true });
        }
        return Promise.reject(new Error(`unexpected request: ${url}`));
      },
    );
    installBundle(fetchJSON);

    await act(async () => {
      root.render(<TestShell initialEntry="/workspace/achievements" />);
    });
    await settle();

    await act(async () => buttonWithText(container, "Pause tracking").click());
    await settle();
    const patchCall = fetchJSON.mock.calls.find(([url]) =>
      String(url).endsWith("/settings"),
    );
    expect(JSON.parse(String((patchCall?.[1] as FetchInit).body))).toEqual({
      tracking_enabled: false,
    });

    await act(async () =>
      buttonWithText(container, "Delete activity metadata").click(),
    );
    expect(
      fetchJSON.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith("/activity") && init?.method === "DELETE",
      ),
    ).toBe(false);
    await act(async () =>
      buttonWithText(container, "Confirm delete activity").click(),
    );
    await settle();
    const deleteCall = fetchJSON.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/activity") && init?.method === "DELETE",
    );
    expect(JSON.parse(String((deleteCall?.[1] as FetchInit).body))).toEqual({
      confirm: true,
    });

    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await act(async () =>
      buttonContaining(container, "Export activity metadata").click(),
    );
    await settle();
    expect(
      fetchJSON.mock.calls.some(([url]) =>
        String(url).endsWith("/activity/export"),
      ),
    ).toBe(true);
  });
});
