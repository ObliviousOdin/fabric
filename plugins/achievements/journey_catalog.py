"""Data-only Fabric Journey V2 catalog.

V1's 54 milestone IDs remain frozen in :mod:`plugins.achievements.catalog` and
are intentionally not imported or rewritten here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Optional


@dataclass(frozen=True)
class FactRequirement:
    key: str
    target: int


@dataclass(frozen=True)
class ActionDefinition:
    kind: str
    label: str
    route: Optional[str] = None
    draft: Optional[str] = None


@dataclass(frozen=True)
class AchievementDefinition:
    id: str
    path_id: str
    capability: str
    title: str
    description: str
    xp: int
    requirements: tuple[FactRequirement, ...]
    action: ActionDefinition
    estimate_minutes: int = 10
    rank_eligible: bool = True
    launch: bool = True
    recommendable: bool = True
    hidden: bool = False
    multi_step: bool = False
    preview_reason: Optional[str] = None


@dataclass(frozen=True)
class PathDefinition:
    id: str
    title: str
    description: str


@dataclass(frozen=True)
class RankDefinition:
    id: str
    label: str
    xp: int
    achievements: int
    families: int


@dataclass(frozen=True)
class OutcomeDefinition:
    id: str
    label: str
    description: str
    preferred_paths: tuple[str, ...]


@dataclass(frozen=True)
class DailyTemplate:
    id: str
    path_id: str
    capability: str
    title: str
    description: str
    why: str
    fact_key: str
    target_delta: int
    estimate_minutes: int
    action: ActionDefinition


CHAT_ROUTE = "/workspace/chat"
SKILLS_ROUTE = "/admin/integrations/skills"
MODELS_ROUTE = "/admin/ai-runtime/models"
AGENTS_ROUTE = "/workspace/agents"
AUTOMATIONS_ROUTE = "/workspace/automations"


def _route(label: str, route: str) -> ActionDefinition:
    return ActionDefinition("route", label, route=route)


def _chat(label: str, draft: str) -> ActionDefinition:
    return ActionDefinition("chat", label, route=CHAT_ROUTE, draft=draft)


def _none(label: str = "Unavailable") -> ActionDefinition:
    return ActionDefinition("none", label)


PATHS: Final[tuple[PathDefinition, ...]] = (
    PathDefinition(
        "conversation", "Conversation", "Turn a useful chat into completed work."
    ),
    PathDefinition(
        "agent_crew",
        "Agent crew",
        "Delegate bounded work and coordinate parallel specialists.",
    ),
    PathDefinition(
        "deep_work", "Deep work", "Build sustained, outcome-oriented Fabric sessions."
    ),
    PathDefinition(
        "model_lab",
        "Model lab",
        "Use multiple configured model providers successfully.",
    ),
    PathDefinition(
        "create", "Create", "Research, make images, and build content workflows."
    ),
    PathDefinition(
        "computer_use",
        "Computer use",
        "Navigate the web and operate interfaces with Fabric.",
    ),
    PathDefinition(
        "automate", "Automate", "Schedule work and prove that recurring runs complete."
    ),
    PathDefinition(
        "skills", "Skills", "Use, combine, and author reusable Fabric skills."
    ),
    PathDefinition(
        "contributor",
        "Contributor",
        "Turn reusable improvements into shared capability.",
    ),
    PathDefinition(
        "anywhere", "Anywhere", "Carry useful work across Fabric surfaces and sessions."
    ),
)


OUTCOMES: Final[tuple[OutcomeDefinition, ...]] = (
    OutcomeDefinition(
        "finish_faster",
        "Finish work faster",
        "Learn a focused chat, research, and computer-use workflow.",
        ("conversation", "computer_use", "deep_work"),
    ),
    OutcomeDefinition(
        "build_agents",
        "Build with agents",
        "Delegate work and coordinate parallel specialists.",
        ("agent_crew", "anywhere", "deep_work"),
    ),
    OutcomeDefinition(
        "create_content",
        "Create content",
        "Research, generate visuals, and develop repeatable creative flows.",
        ("create", "skills", "conversation"),
    ),
    OutcomeDefinition(
        "automate_work",
        "Automate recurring work",
        "Schedule reliable work and grow it into durable capability.",
        ("automate", "skills", "agent_crew"),
    ),
)


RANKS: Final[tuple[RankDefinition, ...]] = (
    RankDefinition("explorer", "Explorer", 0, 0, 0),
    RankDefinition("operator", "Operator", 250, 3, 2),
    RankDefinition("builder", "Builder", 750, 7, 4),
    RankDefinition("orchestrator", "Orchestrator", 1_750, 12, 6),
    RankDefinition("weaver", "Weaver", 3_000, 17, 7),
    RankDefinition("patternmaker", "Patternmaker", 4_500, 23, 8),
)


ACHIEVEMENTS: Final[tuple[AchievementDefinition, ...]] = (
    AchievementDefinition(
        "conversation.first_thread",
        "conversation",
        "conversation",
        "First useful thread",
        "Complete a real Fabric chat turn.",
        50,
        (FactRequirement("successful_turns", 1),),
        _chat(
            "Start in Chat",
            "Help me finish one useful task. Ask only for context you truly need, then complete it.",
        ),
        5,
    ),
    AchievementDefinition(
        "conversation.keep_thread",
        "conversation",
        "conversation",
        "Keep the thread",
        "Complete three useful turns in one conversation.",
        100,
        (FactRequirement("max_turns_per_session", 3),),
        _chat(
            "Continue in Chat",
            "Help me take one task from a first draft through a checked final result.",
        ),
        15,
        multi_step=True,
    ),
    AchievementDefinition(
        "conversation.everywhere",
        "anywhere",
        "anywhere",
        "Fabric everywhere",
        "Complete useful turns on two Fabric surfaces.",
        175,
        (FactRequirement("distinct_surfaces", 2),),
        _chat(
            "Start a thread",
            "Help me start a task I can continue from another Fabric surface.",
        ),
        10,
        multi_step=True,
    ),
    AchievementDefinition(
        "models.chatgpt_online",
        "model_lab",
        "model_lab",
        "ChatGPT online",
        "Complete a successful request with OpenAI.",
        75,
        (FactRequirement("openai_provider_successes", 1),),
        _route("Set up models", MODELS_ROUTE),
        10,
    ),
    AchievementDefinition(
        "models.grok_online",
        "model_lab",
        "model_lab",
        "Grok online",
        "Complete a successful request with xAI.",
        75,
        (FactRequirement("xai_provider_successes", 1),),
        _route("Set up models", MODELS_ROUTE),
        10,
    ),
    AchievementDefinition(
        "models.two_minds",
        "model_lab",
        "model_lab",
        "Two minds",
        "Use two configured model providers successfully.",
        125,
        (FactRequirement("distinct_providers", 2),),
        _route("Open models", MODELS_ROUTE),
        15,
        multi_step=True,
    ),
    AchievementDefinition(
        "skills.skill_spark",
        "skills",
        "skills",
        "Skill spark",
        "Use one Fabric skill in real work.",
        75,
        (FactRequirement("skill_uses", 1),),
        _route("Browse skills", SKILLS_ROUTE),
        5,
    ),
    AchievementDefinition(
        "skills.capability_garden",
        "skills",
        "skills",
        "Capability garden",
        "Use five different Fabric skills.",
        175,
        (FactRequirement("distinct_skills", 5),),
        _route("Browse skills", SKILLS_ROUTE),
        15,
        multi_step=True,
    ),
    AchievementDefinition(
        "memory.remember_recall",
        "conversation",
        "memory",
        "Remember and recall",
        "Store a memory and successfully recall it later.",
        150,
        (FactRequirement("memory_store_recall", 1),),
        _chat(
            "Use memory",
            "Remember one durable preference or fact I choose, then help me verify it can be recalled later.",
        ),
        15,
        multi_step=True,
    ),
    AchievementDefinition(
        "skills.skillsmith",
        "skills",
        "skills",
        "Skillsmith",
        "Author a Fabric skill, then use it successfully.",
        250,
        (FactRequirement("verified_skill_reuse", 1),),
        _route("Open skills", SKILLS_ROUTE),
        30,
        multi_step=True,
    ),
    AchievementDefinition(
        "research.scout",
        "create",
        "research",
        "Scout",
        "Complete a Fabric turn that uses web search.",
        75,
        (FactRequirement("research_completed_turns", 1),),
        _chat(
            "Research in Chat",
            "Research one current question for me and give me a concise, source-backed answer.",
        ),
        10,
    ),
    AchievementDefinition(
        "research.brief",
        "create",
        "research",
        "Research brief",
        "Build a sourced brief with extracts and a saved artifact.",
        0,
        (FactRequirement("research_completed_turns", 1),),
        _chat(
            "Build a brief",
            "Research a topic I choose, compare the strongest sources, and turn the result into a practical brief.",
        ),
        20,
        rank_eligible=False,
        launch=False,
        recommendable=False,
        multi_step=True,
        preview_reason="Extract and saved-artifact evidence is not yet available in the closed event vocabulary.",
    ),
    AchievementDefinition(
        "creative.image_maker",
        "create",
        "create",
        "Image maker",
        "Generate one image successfully.",
        75,
        (FactRequirement("image_successes", 1),),
        _chat(
            "Create an image",
            "Help me define and generate one useful image for a real project.",
        ),
        10,
        recommendable=False,
    ),
    AchievementDefinition(
        "creative.art_director",
        "create",
        "create",
        "Art director",
        "Generate three images across two active days.",
        150,
        (FactRequirement("image_successes", 3), FactRequirement("image_days", 2)),
        _chat(
            "Direct an image",
            "Help me refine an image through a clear visual brief and a deliberate second pass.",
        ),
        30,
        recommendable=False,
        multi_step=True,
    ),
    AchievementDefinition(
        "browser.navigator",
        "computer_use",
        "computer_use",
        "Navigator",
        "Navigate, then complete three browser actions in one turn.",
        100,
        (FactRequirement("browser_navigation_turns", 1),),
        _chat(
            "Browse with Fabric",
            "Open a useful public webpage, inspect it, and summarize the important information.",
        ),
        10,
    ),
    AchievementDefinition(
        "cua.hands_on",
        "computer_use",
        "computer_use",
        "Hands on",
        "Complete three computer-use actions in one turn.",
        125,
        (FactRequirement("computer_use_turns", 1),),
        _chat(
            "Use my computer",
            "Help me complete one safe, reversible task with computer use. Pause before any consequential action.",
        ),
        10,
    ),
    AchievementDefinition(
        "browser.web_operator",
        "computer_use",
        "computer_use",
        "Web operator",
        "Complete five browser or computer-use workflows across three sessions.",
        225,
        (
            FactRequirement("browser_workflows", 5),
            FactRequirement("browser_workflow_sessions", 3),
        ),
        _chat(
            "Run a web workflow",
            "Complete a small multi-step web task, verify the result, and report what changed.",
        ),
        20,
        multi_step=True,
    ),
    AchievementDefinition(
        "content.linkedin_launch",
        "create",
        "create",
        "LinkedIn launch",
        "Publish a LinkedIn post created with Fabric.",
        0,
        (FactRequirement("linkedin_launches", 1),),
        _chat(
            "Create a LinkedIn post",
            "Help me draft and review a useful LinkedIn post. Do not publish it until I explicitly approve the final text.",
        ),
        rank_eligible=False,
        launch=False,
        recommendable=False,
        preview_reason="External publishing is not safely observable and remains self-attested.",
    ),
    AchievementDefinition(
        "voice.voice_on",
        "create",
        "voice",
        "Voice on",
        "Complete one successful voice transcription.",
        75,
        (FactRequirement("voice_transcriptions", 1),),
        _chat("Try voice", "Help me complete a useful task from a spoken prompt."),
        10,
    ),
    AchievementDefinition(
        "voice.full_duplex",
        "create",
        "voice",
        "Full duplex",
        "Use speech input and spoken output in one turn.",
        0,
        (FactRequirement("full_duplex_turns", 1),),
        _chat(
            "Start a voice exchange",
            "Use voice input and ask Fabric to answer with speech for one useful exchange.",
        ),
        15,
        rank_eligible=False,
        launch=False,
        recommendable=False,
        multi_step=True,
        preview_reason="Voice input and output cannot yet be correlated safely across every surface.",
    ),
    AchievementDefinition(
        "automation.clock_set",
        "automate",
        "automate",
        "Clock set",
        "Create a schedule and complete its first successful run.",
        125,
        (FactRequirement("automation_schedule_run", 1),),
        _route("Open automations", AUTOMATIONS_ROUTE),
        10,
    ),
    AchievementDefinition(
        "automation.reliable_loop",
        "automate",
        "automate",
        "Reliable loop",
        "Complete scheduled work on seven consecutive days.",
        250,
        (FactRequirement("automation_run_day_streak", 7),),
        _route("Open automations", AUTOMATIONS_ROUTE),
        30,
        multi_step=True,
    ),
    AchievementDefinition(
        "automation.quiet_machinery",
        "automate",
        "automate",
        "Quiet machinery",
        "Complete thirty scheduled runs across fourteen days with at least 90% recent reliability.",
        400,
        (
            FactRequirement("automation_runs", 30),
            FactRequirement("automation_run_days", 14),
            FactRequirement("automation_reliability_percent", 90),
        ),
        _route("Open automations", AUTOMATIONS_ROUTE),
        60,
        multi_step=True,
    ),
    AchievementDefinition(
        "agents.first_delegate",
        "agent_crew",
        "agent_crew",
        "First delegate",
        "Delegate one bounded task and receive a successful result.",
        100,
        (FactRequirement("successful_subagents", 1),),
        _chat(
            "Delegate in Chat",
            "Delegate one bounded research or review task to a subagent, then use its result in your answer.",
        ),
        10,
    ),
    AchievementDefinition(
        "agents.parallel_crew",
        "agent_crew",
        "agent_crew",
        "Parallel crew",
        "Complete a run with three concurrent agents and at least 80% success.",
        200,
        (FactRequirement("parallel_crew_runs", 1),),
        _chat(
            "Run a parallel crew",
            "Split one objective into two independent subagent tasks, run them in parallel, and synthesize their results.",
        ),
        20,
        multi_step=True,
    ),
    AchievementDefinition(
        "agents.orchestra",
        "agent_crew",
        "agent_crew",
        "Orchestra",
        "Complete a run with eight agents, peak concurrency three, and at least 80% success.",
        350,
        (FactRequirement("orchestra_runs", 1),),
        _route("Open agents", AGENTS_ROUTE),
        30,
        multi_step=True,
    ),
    AchievementDefinition(
        "agents.swarm_commander",
        "agent_crew",
        "agent_crew",
        "Swarm commander",
        "Complete one objective with twenty agents and at least 80% success.",
        500,
        (FactRequirement("swarm_runs", 1),),
        _route("Open agents", AGENTS_ROUTE),
        60,
        recommendable=False,
        hidden=True,
        multi_step=True,
    ),
    AchievementDefinition(
        "sessions.parallel_pilot",
        "anywhere",
        "anywhere",
        "Parallel pilot",
        "Run two successful Fabric sessions with overlapping work.",
        250,
        (FactRequirement("parallel_session_runs", 1),),
        _chat(
            "Start parallel work",
            "Plan two independent Fabric sessions that can run safely in parallel.",
        ),
        20,
        multi_step=True,
    ),
    AchievementDefinition(
        "focus.focus_block",
        "deep_work",
        "deep_work",
        "Focus block",
        "Complete a useful outcome during 30 active minutes.",
        75,
        (FactRequirement("focus_blocks", 1),),
        _chat(
            "Start a focus block",
            "Help me define one concrete outcome for a focused 30-minute working session, then work toward it.",
        ),
        30,
    ),
    AchievementDefinition(
        "focus.deep_work",
        "deep_work",
        "deep_work",
        "Deep work",
        "Complete a useful outcome during 120 active minutes.",
        175,
        (FactRequirement("deep_work_blocks", 1),),
        _chat(
            "Start deep work",
            "Help me structure a substantial task into checkpoints and complete it in this working session.",
        ),
        120,
        recommendable=False,
        multi_step=True,
    ),
    AchievementDefinition(
        "focus.long_haul",
        "deep_work",
        "deep_work",
        "Long haul",
        "Complete five elapsed hours, 300 active minutes, and twenty meaningful outcomes.",
        400,
        (FactRequirement("long_haul_runs", 1),),
        _chat(
            "Plan a long session",
            "Plan a long-running Fabric session with explicit checkpoints, verification, and a final completed output.",
        ),
        300,
        recommendable=False,
        hidden=True,
        multi_step=True,
    ),
    AchievementDefinition(
        "contribution.verified_builder",
        "contributor",
        "contributor",
        "Verified builder",
        "Author a skill and successfully reuse it three times later.",
        175,
        (FactRequirement("verified_skill_reuse", 3),),
        _route("Build a skill", SKILLS_ROUTE),
        45,
        multi_step=True,
    ),
    AchievementDefinition(
        "contribution.fabric_contributor",
        "contributor",
        "contributor",
        "Fabric contributor",
        "Land an explicitly verified improvement to Fabric.",
        0,
        (FactRequirement("verified_contributions", 1),),
        _none(),
        rank_eligible=False,
        launch=False,
        recommendable=False,
        preview_reason="Upstream verification requires a future explicit opt-in check.",
    ),
    AchievementDefinition(
        "contribution.patternmaker",
        "contributor",
        "contributor",
        "Contribution patternmaker",
        "Land three explicitly verified Fabric improvements.",
        0,
        (FactRequirement("verified_contributions", 3),),
        _none(),
        rank_eligible=False,
        launch=False,
        recommendable=False,
        hidden=True,
        preview_reason="Upstream verification requires a future explicit opt-in check.",
    ),
)


ACHIEVEMENTS_BY_ID: Final[dict[str, AchievementDefinition]] = {
    item.id: item for item in ACHIEVEMENTS
}
PATHS_BY_ID: Final[dict[str, PathDefinition]] = {item.id: item for item in PATHS}
OUTCOMES_BY_ID: Final[dict[str, OutcomeDefinition]] = {
    item.id: item for item in OUTCOMES
}


STARTER_ACHIEVEMENT_IDS: Final[tuple[str, ...]] = (
    "conversation.first_thread",
    "starter.tool_assist",
    "agents.first_delegate",
)


DAILY_TEMPLATES: Final[tuple[DailyTemplate, ...]] = (
    DailyTemplate(
        "daily.useful_chat",
        "conversation",
        "conversation",
        "Finish one useful chat",
        "Complete one real task turn with Fabric.",
        "A completed thread is the foundation for every advanced workflow.",
        "successful_turns",
        1,
        5,
        _chat("Start in Chat", "Help me complete one useful task in this chat."),
    ),
    DailyTemplate(
        "daily.research",
        "create",
        "research",
        "Research one question",
        "Use Fabric web research and finish the turn.",
        "Research is a fast way to learn tool-assisted work.",
        "research_completed_turns",
        1,
        10,
        _chat(
            "Research in Chat",
            "Research one practical question and give me a concise source-backed answer.",
        ),
    ),
    DailyTemplate(
        "daily.browse",
        "computer_use",
        "computer_use",
        "Complete a browser task",
        "Navigate and inspect one useful webpage.",
        "Browser work turns chat into direct action.",
        "browser_navigation_turns",
        1,
        10,
        _chat(
            "Browse with Fabric",
            "Open a useful public page, inspect it, and summarize what matters.",
        ),
    ),
    DailyTemplate(
        "daily.skill",
        "skills",
        "skills",
        "Use one skill",
        "Apply an installed skill to real work.",
        "Skills reveal Fabric capabilities without expanding the core.",
        "skill_uses",
        1,
        10,
        _route("Browse skills", SKILLS_ROUTE),
    ),
    DailyTemplate(
        "daily.delegate",
        "agent_crew",
        "agent_crew",
        "Delegate one bounded task",
        "Receive one successful subagent result.",
        "Delegation is the first step toward orchestration.",
        "successful_subagents",
        1,
        10,
        _chat(
            "Delegate in Chat",
            "Delegate one bounded research or review task and use the result.",
        ),
    ),
)


def _validate() -> None:
    ids = [item.id for item in ACHIEVEMENTS]
    if len(ids) != len(set(ids)):
        raise ValueError("Journey achievement ids must be unique")
    if any(item.path_id not in PATHS_BY_ID for item in ACHIEVEMENTS):
        raise ValueError("Journey achievement references an unknown path")
    if any(item.xp < 0 for item in ACHIEVEMENTS):
        raise ValueError("Journey XP cannot be negative")
    if any(
        not item.launch and (item.xp or item.rank_eligible) for item in ACHIEVEMENTS
    ):
        raise ValueError("Preview achievements cannot award rank XP")
    launch = [item for item in ACHIEVEMENTS if item.launch and item.rank_eligible]
    if sum(item.xp for item in launch) < RANKS[-1].xp:
        raise ValueError("Launch catalog cannot reach Patternmaker XP")
    if len(launch) < RANKS[-1].achievements:
        raise ValueError("Launch catalog cannot reach Patternmaker count")
    if len({item.path_id for item in launch}) < RANKS[-1].families:
        raise ValueError("Launch catalog cannot reach Patternmaker breadth")


_validate()


__all__ = [
    "ACHIEVEMENTS",
    "ACHIEVEMENTS_BY_ID",
    "DAILY_TEMPLATES",
    "OUTCOMES",
    "OUTCOMES_BY_ID",
    "PATHS",
    "PATHS_BY_ID",
    "RANKS",
    "AchievementDefinition",
    "ActionDefinition",
    "DailyTemplate",
    "FactRequirement",
]
