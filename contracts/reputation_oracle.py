# v0.2.18
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *

import json
import typing
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCORE_UNKNOWN    = 0
SCORE_CRITICAL   = 1
SCORE_POOR       = 2
SCORE_MIXED      = 3
SCORE_GOOD       = 4
SCORE_EXCELLENT  = 5
MAX_SCORE        = 5

CONF_LOW    = 1
CONF_MEDIUM = 2
CONF_HIGH   = 3
MAX_CONFIDENCE = 3

MAX_SIGNALS        = 32
MAX_SOURCES        = 8
MAX_HISTORY        = 24
MAX_SUBSCRIBERS    = 32
MAX_KEY_LEN        = 64
MAX_VALUE_LEN      = 512
MAX_CRITERIA_LEN   = 2048
MAX_ENTITY_LEN     = 256
MAX_PAGE_CHARS     = 20000

FAILURE_DEGRADE_THRESHOLD = 3

ERR_EXPECTED  = "EXPECTED"
ERR_EXTERNAL  = "EXTERNAL"
ERR_TRANSIENT = "TRANSIENT"
ERR_LLM       = "LLM_ERROR"


# ---------------------------------------------------------------------------
# Storage types
# ---------------------------------------------------------------------------
@allow_storage
@dataclass
class Signal:
    key: str
    value: str
    polarity: str

@allow_storage
@dataclass
class Assessment:
    version: u32
    assessed_at: str
    score: u8
    confidence: u8
    summary: str
    diff_json: str

@allow_storage
@dataclass
class Source:
    url: str
    label: str

@allow_storage
@dataclass
class Subscription:
    subscriber: Address
    alert_below: u8

@allow_storage
@dataclass
class Profile:
    owner: Address
    entity_name: str
    criteria: str
    min_alert_score: u8
    cooldown_seconds: u64
    active: bool
    scored: bool
    version: u32
    score: u8
    confidence: u8
    signals_digest: str
    last_assessed_at: str
    last_change_at: str
    consecutive_failures: u32
    total_assessments: u32
    sources: DynArray[Source]
    signals: DynArray[Signal]
    history: DynArray[Assessment]
    subscribers: DynArray[Subscription]


# ---------------------------------------------------------------------------
# Subscriber interface
# ---------------------------------------------------------------------------
@gl.contract_interface
class IReputationSubscriber:
    class View:
        pass

    class Write:
        def on_reputation_change(
            self,
            profile_id: u256,
            version: u32,
            old_score: u8,
            new_score: u8,
            confidence: u8,
            summary: str,
            diff_json: str,
        ) -> None: ...


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
class ProfileCreated(gl.Event):
    def __init__(self, profile_id: u256, owner: Address, entity_name: str, /, **blob): ...

class ProfileAssessed(gl.Event):
    def __init__(self, profile_id: u256, /, **blob): ...

class ReputationChanged(gl.Event):
    def __init__(self, profile_id: u256, old_score: u8, new_score: u8, /, **blob): ...

class ProfileScored(gl.Event):
    """Emitted the first time a profile receives a consensus-agreed score."""
    def __init__(self, profile_id: u256, score: u8, confidence: u8, /, **blob): ...

class ProfileDegraded(gl.Event):
    def __init__(self, profile_id: u256, /, **blob): ...

class ProfileActiveChanged(gl.Event):
    def __init__(self, profile_id: u256, active: bool, /, **blob): ...

class ProfileSensitivityChanged(gl.Event):
    def __init__(self, profile_id: u256, min_alert_score: u8, /, **blob): ...


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------
def build_extraction_prompt(
    page_text: str,
    criteria: str,
    entity_name: str,
    anchors: list[dict],
) -> str:
    if len(anchors) > 0:
        anchor_block = (
            "ESTABLISHED SIGNALS from the last agreed assessment:\n"
            + "\n".join(
                f'- {a["key"]}: {a["value"]} ({a.get("polarity", "neutral")})'
                for a in anchors
            )
            + "\n\nANCHORING RULES:\n"
            "a. Reuse an established key verbatim whenever that signal still exists.\n"
            "b. If an established signal is still true, reproduce its value VERBATIM.\n"
            "c. Only write a new value when the substance itself has changed."
        )
    else:
        anchor_block = (
            "There are no established signals yet. Create stable, descriptive "
            "snake_case keys and concise values."
        )

    return f"""You extract a canonical set of reputation signals about an entity from web content.

ENTITY: {entity_name}

ASSESSMENT CRITERIA:
{criteria}

{anchor_block}

RULES
1. Extract only signals relevant to the criteria.
2. For each signal, assign polarity: "positive", "negative", or "neutral".
3. At most {MAX_SIGNALS} signals.
4. Keys must be snake_case, under {MAX_KEY_LEN} chars.
5. Values must be concise, under {MAX_VALUE_LEN} chars.
6. Ignore ads, navigation, timestamps, view counters.
7. Order signals alphabetically by key.

Return ONLY this JSON, no prose:
{{"signals": [{{"key": "...", "value": "...", "polarity": "positive|negative|neutral"}}]}}

CONTENT:
{page_text}
"""


def build_scoring_prompt(
    criteria: str,
    entity_name: str,
    before: list[dict],
    after: list[dict],
) -> str:
    return f"""You score an entity's reputation based on signal changes.

ENTITY: {entity_name}

CRITERIA:
{criteria}

PREVIOUS SIGNALS:
{json.dumps(before, sort_keys=True)}

CURRENT SIGNALS:
{json.dumps(after, sort_keys=True)}

SCORING:
1 = CRITICAL: Severe concerns, fraud, major violations
2 = POOR: Multiple negative signals
3 = MIXED: Contradictory signals
4 = GOOD: Mostly positive
5 = EXCELLENT: Strong positive, no concerns

CONFIDENCE:
1 = LOW: Few sources
2 = MEDIUM: Reasonable evidence
3 = HIGH: Strong evidence

Return ONLY this JSON, no prose:
{{"score": <1-5>, "confidence": <1-3>, "summary": "<under 200 chars>", "changes": [{{"key": "...", "before": "...", "after": "...", "impact": "..."}}]}}
"""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def canonical_signals_digest(signals: list[dict]) -> str:
    normalised = sorted(
        (str(s.get("key", "")), str(s.get("value", "")), str(s.get("polarity", "")))
        for s in signals
    )
    payload = json.dumps(normalised, separators=(",", ":"), ensure_ascii=False)
    return Keccak256(payload.encode("utf-8")).hexdigest()


def parse_json_envelope(raw: typing.Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError(f"{ERR_LLM}: not text or object")
    text = raw.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    raise ValueError(f"{ERR_LLM}: not a JSON object")


def sanitise_signals(raw_signals: typing.Any) -> list[dict]:
    if not isinstance(raw_signals, list):
        raise ValueError(f"{ERR_LLM}: 'signals' was not a list")
    cleaned: dict[str, dict] = {}
    for item in raw_signals:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()[:MAX_KEY_LEN]
        if key == "":
            continue
        value = " ".join(str(item.get("value", "")).split())[:MAX_VALUE_LEN]
        polarity = str(item.get("polarity", "neutral")).strip().lower()
        if polarity not in ("positive", "negative", "neutral"):
            polarity = "neutral"
        if key not in cleaned:
            cleaned[key] = {"key": key, "value": value, "polarity": polarity}
    ordered = sorted(cleaned.items())[:MAX_SIGNALS]
    return [v for _, v in ordered]


def current_datetime() -> str:
    message = getattr(gl, "message", None)
    raw = getattr(message, "raw", None)
    value = getattr(raw, "datetime", None)
    if isinstance(value, str) and value != "":
        return value
    mapping = getattr(gl, "message_raw", None)
    if isinstance(mapping, dict):
        fallback = mapping.get("datetime")
        if isinstance(fallback, str) and fallback != "":
            return fallback
    return ""


def clamp_score(raw: typing.Any) -> int:
    try:
        value = int(raw)
    except Exception:
        return SCORE_MIXED
    if value < SCORE_CRITICAL:
        return SCORE_CRITICAL
    if value > MAX_SCORE:
        return MAX_SCORE
    return value


def clamp_confidence(raw: typing.Any) -> int:
    try:
        value = int(raw)
    except Exception:
        return CONF_LOW
    if value < CONF_LOW:
        return CONF_LOW
    if value > MAX_CONFIDENCE:
        return MAX_CONFIDENCE
    return value


# ---------------------------------------------------------------------------
# Envelope packing
# ---------------------------------------------------------------------------
def pack_error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, sort_keys=True)


def pack_observation(raw_model_output: str) -> str:
    try:
        signals = sanitise_signals(
            parse_json_envelope(raw_model_output).get("signals")
        )
    except Exception as exc:
        return pack_error(f"{ERR_LLM}: {exc}")
    return json.dumps({"ok": True, "signals": signals}, sort_keys=True)


def pack_verdict(raw_model_output: str) -> str:
    try:
        parsed = parse_json_envelope(raw_model_output)
    except Exception as exc:
        return pack_error(f"{ERR_LLM}: {exc}")
    changes = parsed.get("changes")
    if not isinstance(changes, list):
        changes = []
    return json.dumps(
        {
            "ok": True,
            "score": clamp_score(parsed.get("score")),
            "confidence": clamp_confidence(parsed.get("confidence")),
            "summary": " ".join(str(parsed.get("summary", "")).split())[:200],
            "changes": changes[:MAX_SIGNALS],
        },
        sort_keys=True,
    )


# ---------------------------------------------------------------------------
# Equivalence principles
# ---------------------------------------------------------------------------
EQ_OBSERVE = (
    "Both outputs extract reputation signals from the same web content. "
    "They are equivalent if they identify the same signals with the same meaning. "
    "Ignore differences in key naming, ordering, whitespace. "
    "Values differing only in phrasing are equivalent. "
    "Values differing in substance are NOT equivalent. "
    "Polarity differences are NEVER equivalent. "
    "If one reports an error and the other does not, they are NOT equivalent."
)

EQ_JUDGE = (
    "Both outputs score the same reputation change. "
    "They are equivalent if score and confidence values match exactly. "
    "Differences in summary wording are irrelevant. "
    "A different score or confidence means NOT equivalent."
)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------
class ReputationOracle(gl.Contract):
    """Registry of entity reputation profiles and their verified assessment history."""
    
    profiles: TreeMap[u256, Profile]
    next_id: u256
    admin: Address

    def __init__(self):
        self.next_id = u256(1)
        self.admin = gl.message.sender_address

    # -- internal helpers ---------------------------------------------------

    def _require_profile(self, profile_id: u256) -> Profile:
        profile = self.profiles.get(profile_id)
        if profile is None:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: unknown profile {profile_id}")
        return profile

    def _require_owner(self, profile: Profile) -> None:
        if profile.owner != gl.message.sender_address:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: caller is not the profile owner")

    def _signals_to_list(self, profile: Profile) -> list[dict]:
        return [
            {"key": str(s.key), "value": str(s.value), "polarity": str(s.polarity)}
            for s in profile.signals
        ]

    def _sources_to_list(self, profile: Profile) -> list[dict]:
        return [
            {"url": str(s.url), "label": str(s.label)}
            for s in profile.sources
        ]

    def _store_signals(self, profile: Profile, signals: list[dict]) -> None:
        profile.signals.clear()
        for s in signals:
            entry = profile.signals.append_new_get()
            entry.key = s["key"]
            entry.value = s["value"]
            entry.polarity = s.get("polarity", "neutral")

    def _append_history(self, profile: Profile, record: Assessment) -> None:
        if len(profile.history) >= MAX_HISTORY:
            retained = [profile.history[i] for i in range(1, len(profile.history))]
            profile.history.clear()
            for item in retained:
                profile.history.append(item)
        profile.history.append(record)

    def _parse_ts(self, value: str) -> int:
        import datetime
        try:
            return int(
                datetime.datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).timestamp()
            )
        except Exception:
            return 0

    # -- consensus rounds ---------------------------------------------------

    def _observe(
        self,
        url: str,
        criteria: str,
        entity_name: str,
        anchors: list[dict],
    ) -> dict:
        """Round 1: fetch the page and extract signals, under consensus."""
        def leader() -> str:
            try:
                page = gl.nondet.web.render(url, mode="text")
            except Exception as exc:
                return pack_error(f"{ERR_EXTERNAL}: fetch failed: {exc}")
            
            page_text = str(page)
            if len(page_text.strip()) == 0:
                return pack_error(f"{ERR_EXTERNAL}: page rendered empty")
            
            try:
                raw = gl.nondet.exec_prompt(
                    build_extraction_prompt(
                        page_text[:MAX_PAGE_CHARS], criteria, entity_name, anchors
                    ),
                    response_format="text",
                )
            except Exception as exc:
                return pack_error(f"{ERR_TRANSIENT}: model call failed: {exc}")
            
            return pack_observation(raw)

        return json.loads(gl.eq_principle.prompt_comparative(leader, EQ_OBSERVE))

    def _judge(
        self,
        criteria: str,
        entity_name: str,
        before: list[dict],
        after: list[dict],
    ) -> dict:
        """Round 2: score the reputation based on signal changes."""
        def leader() -> str:
            try:
                raw = gl.nondet.exec_prompt(
                    build_scoring_prompt(criteria, entity_name, before, after),
                    response_format="text",
                )
            except Exception as exc:
                return pack_error(f"{ERR_TRANSIENT}: model call failed: {exc}")
            return pack_verdict(raw)

        return json.loads(gl.eq_principle.prompt_comparative(leader, EQ_JUDGE))

    def _cooldown_remaining(self, profile: Profile, now: str) -> int:
        now_ts = self._parse_ts(now)
        last_ts = self._parse_ts(str(profile.last_assessed_at))
        if now_ts < last_ts:
            return 0
        elapsed = now_ts - last_ts
        needed = int(profile.cooldown_seconds)
        if elapsed < needed and needed > 0:
            return needed - elapsed
        return 0

    def _notify(
        self, profile: Profile, profile_id: u256, record: Assessment, old_score: int
    ) -> None:
        for entry in profile.subscribers:
            if int(record.score) < int(entry.alert_below):
                try:
                    IReputationSubscriber(entry.subscriber).on_reputation_change(
                        profile_id,
                        record.version,
                        u8(old_score),
                        record.score,
                        record.confidence,
                        str(record.summary),
                        str(record.diff_json),
                        on="finalized",
                    )
                except Exception:
                    pass

    # -- lifecycle ----------------------------------------------------------

    @gl.public.write
    def create_profile(
        self,
        entity_name: str,
        url: str,
        criteria: str,
        min_alert_score: int = SCORE_MIXED,
        cooldown_seconds: int = 3600,
    ) -> u256:
        """Register an entity and take its baseline signal snapshot.

        The profile is created with scored=False, meaning it is NOT yet
        reliable. The first call to assess() will run the scoring round
        and transition the profile to scored=True, at which point it
        becomes reliable (assuming it is active and not degraded).
        """
        if len(entity_name) == 0 or len(entity_name) > MAX_ENTITY_LEN:
            raise gl.vm.UserError(
                f"{ERR_EXPECTED}: entity_name must be 1..{MAX_ENTITY_LEN} chars"
            )
        if len(criteria) == 0 or len(criteria) > MAX_CRITERIA_LEN:
            raise gl.vm.UserError(
                f"{ERR_EXPECTED}: criteria must be 1..{MAX_CRITERIA_LEN} chars"
            )
        if not (url.startswith("http://") or url.startswith("https://")):
            raise gl.vm.UserError(f"{ERR_EXPECTED}: url must be http(s)")
        if min_alert_score < SCORE_CRITICAL or min_alert_score > MAX_SCORE:
            raise gl.vm.UserError(
                f"{ERR_EXPECTED}: min_alert_score must be {SCORE_CRITICAL}..{MAX_SCORE}"
            )
        if cooldown_seconds < 0:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: cooldown_seconds must be >= 0")

        # Baseline signal extraction (round 1 only)
        result = self._observe(url, criteria, entity_name, [])
        if not result.get("ok", False):
            raise gl.vm.UserError(
                str(result.get("error", f"{ERR_EXTERNAL}: baseline failed"))
            )

        signals = result["signals"]
        now = current_datetime()
        profile_id = self.next_id
        self.next_id = u256(int(self.next_id) + 1)

        profile = self.profiles.get_or_insert_default(profile_id)
        profile.owner = gl.message.sender_address
        profile.entity_name = entity_name
        profile.criteria = criteria
        profile.min_alert_score = u8(min_alert_score)
        profile.cooldown_seconds = u64(cooldown_seconds)
        profile.active = True
        profile.scored = False
        profile.version = u32(1)
        profile.score = u8(SCORE_UNKNOWN)
        profile.confidence = u8(CONF_LOW)
        profile.signals_digest = canonical_signals_digest(signals)
        profile.last_assessed_at = now
        profile.last_change_at = now
        profile.consecutive_failures = u32(0)
        profile.total_assessments = u32(0)

        # Store single source
        entry = profile.sources.append_new_get()
        entry.url = url
        entry.label = "primary"

        self._store_signals(profile, signals)
        ProfileCreated(profile_id, gl.message.sender_address, entity_name).emit()
        return profile_id

    @gl.public.write
    def assess(self, profile_id: u256) -> None:
        """Re-assess a profile's reputation and record any changes.

        If this is the first assessment (scored=False), the scoring round
        always runs regardless of the digest gate, so the profile receives
        its initial consensus-agreed score and transitions to reliable.
        """
        profile = self._require_profile(profile_id)
        if not profile.active:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: profile {profile_id} is paused")

        now = current_datetime()
        remaining = self._cooldown_remaining(profile, now)
        if remaining > 0:
            raise gl.vm.UserError(
                f"{ERR_EXPECTED}: cooldown active, {remaining}s remaining"
            )

        # Get the primary source URL
        if len(profile.sources) == 0:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: no sources configured")
        
        url = str(profile.sources[0].url)
        criteria = str(profile.criteria)
        entity_name = str(profile.entity_name)
        before = self._signals_to_list(profile)
        old_score = int(profile.score)
        was_unscored = not bool(profile.scored)

        # Round 1: fetch + extract signals
        observed = self._observe(url, criteria, entity_name, before)
        profile.total_assessments = u32(int(profile.total_assessments) + 1)
        profile.last_assessed_at = now

        if not observed.get("ok", False):
            profile.consecutive_failures = u32(int(profile.consecutive_failures) + 1)
            if int(profile.consecutive_failures) == FAILURE_DEGRADE_THRESHOLD:
                ProfileDegraded(
                    profile_id, reason=str(observed.get("error", "unknown"))
                ).emit()
            ProfileAssessed(profile_id, changed=False, ok=False).emit()
            return

        profile.consecutive_failures = u32(0)
        after = observed["signals"]

        # Deterministic gate: skip round 2 ONLY if we already have a score
        # and the signals have not changed.
        digest = canonical_signals_digest(after)
        signals_changed = digest != str(profile.signals_digest)

        if not signals_changed and not was_unscored:
            # No change and already scored — nothing to do
            ProfileAssessed(profile_id, changed=False, ok=True).emit()
            return

        # Round 2: score the signals
        # Always runs if: (a) signals changed, OR (b) profile was unscored
        verdict = self._judge(criteria, entity_name, before, after)

        if not verdict.get("ok", False):
            ProfileAssessed(
                profile_id, changed=True, ok=False,
                error=str(verdict.get("error", ""))
            ).emit()
            return

        new_score = int(verdict["score"])
        confidence = int(verdict["confidence"])

        # Update signals
        self._store_signals(profile, after)
        profile.signals_digest = digest

        # If this was the first scoring, transition to scored
        if was_unscored:
            profile.scored = True
            profile.score = u8(new_score)
            profile.confidence = u8(confidence)
            profile.version = u32(int(profile.version) + 1)
            profile.last_change_at = now

            diff_json = json.dumps(verdict.get("changes", []), sort_keys=True)
            record = Assessment(
                version=profile.version,
                assessed_at=now,
                score=u8(new_score),
                confidence=u8(confidence),
                summary=str(verdict.get("summary", "")),
                diff_json=diff_json,
            )
            self._append_history(profile, record)

            ProfileScored(profile_id, u8(new_score), u8(confidence)).emit()
            ReputationChanged(
                profile_id, u8(SCORE_UNKNOWN), u8(new_score),
                summary=str(verdict.get("summary", "")),
            ).emit()

            if new_score < int(profile.min_alert_score):
                self._notify(profile, profile_id, record, SCORE_UNKNOWN)

            ProfileAssessed(profile_id, changed=True, ok=True).emit()
            return

        # Subsequent assessments: only record if score changed
        score_changed = new_score != old_score

        if score_changed:
            profile.score = u8(new_score)
            profile.confidence = u8(confidence)
            profile.version = u32(int(profile.version) + 1)
            profile.last_change_at = now

            diff_json = json.dumps(verdict.get("changes", []), sort_keys=True)
            record = Assessment(
                version=profile.version,
                assessed_at=now,
                score=u8(new_score),
                confidence=u8(confidence),
                summary=str(verdict.get("summary", "")),
                diff_json=diff_json,
            )
            self._append_history(profile, record)
            ReputationChanged(
                profile_id, u8(old_score), u8(new_score),
                summary=str(verdict.get("summary", "")),
            ).emit()

            if new_score < int(profile.min_alert_score):
                self._notify(profile, profile_id, record, old_score)

        ProfileAssessed(profile_id, changed=score_changed, ok=True).emit()

    # -- subscriptions ------------------------------------------------------

    @gl.public.write
    def subscribe(self, profile_id: u256, alert_below: int = SCORE_MIXED) -> None:
        if alert_below < SCORE_CRITICAL or alert_below > MAX_SCORE:
            raise gl.vm.UserError(
                f"{ERR_EXPECTED}: alert_below must be {SCORE_CRITICAL}..{MAX_SCORE}"
            )
        profile = self._require_profile(profile_id)
        if len(profile.subscribers) >= MAX_SUBSCRIBERS:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: subscriber limit reached")
        caller = gl.message.sender_address
        for existing in profile.subscribers:
            if existing.subscriber == caller:
                raise gl.vm.UserError(f"{ERR_EXPECTED}: already subscribed")
        entry = profile.subscribers.append_new_get()
        entry.subscriber = caller
        entry.alert_below = u8(alert_below)

    @gl.public.write
    def unsubscribe(self, profile_id: u256) -> None:
        profile = self._require_profile(profile_id)
        caller = gl.message.sender_address
        retained = [
            (e.subscriber, int(e.alert_below))
            for e in profile.subscribers
            if e.subscriber != caller
        ]
        if len(retained) == len(profile.subscribers):
            raise gl.vm.UserError(f"{ERR_EXPECTED}: not subscribed")
        profile.subscribers.clear()
        for address, floor in retained:
            entry = profile.subscribers.append_new_get()
            entry.subscriber = address
            entry.alert_below = u8(floor)

    # -- owner controls -----------------------------------------------------

    @gl.public.write
    def set_active(self, profile_id: u256, active: bool) -> None:
        profile = self._require_profile(profile_id)
        self._require_owner(profile)
        if bool(profile.active) == active:
            return
        profile.active = active
        ProfileActiveChanged(profile_id, active).emit()

    @gl.public.write
    def set_min_alert_score(self, profile_id: u256, min_alert_score: int) -> None:
        if min_alert_score < SCORE_CRITICAL or min_alert_score > MAX_SCORE:
            raise gl.vm.UserError(
                f"{ERR_EXPECTED}: min_alert_score must be {SCORE_CRITICAL}..{MAX_SCORE}"
            )
        profile = self._require_profile(profile_id)
        self._require_owner(profile)
        if min_alert_score < int(profile.min_alert_score):
            raise gl.vm.UserError(
                f"{ERR_EXPECTED}: min_alert_score may only be raised "
                f"(current {int(profile.min_alert_score)}, requested {min_alert_score})"
            )
        if min_alert_score == int(profile.min_alert_score):
            return
        profile.min_alert_score = u8(min_alert_score)
        ProfileSensitivityChanged(profile_id, u8(min_alert_score)).emit()

    @gl.public.write
    def set_cooldown(self, profile_id: u256, cooldown_seconds: int) -> None:
        if cooldown_seconds < 0:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: cooldown_seconds must be >= 0")
        profile = self._require_profile(profile_id)
        self._require_owner(profile)
        if cooldown_seconds > int(profile.cooldown_seconds):
            raise gl.vm.UserError(
                f"{ERR_EXPECTED}: cooldown_seconds may only be lowered "
                f"(current {int(profile.cooldown_seconds)}, requested {cooldown_seconds})"
            )
        profile.cooldown_seconds = u64(cooldown_seconds)

    @gl.public.write
    def transfer_profile(self, profile_id: u256, new_owner: Address) -> None:
        profile = self._require_profile(profile_id)
        self._require_owner(profile)
        try:
            owner = new_owner if isinstance(new_owner, Address) else Address(new_owner)
        except Exception as exc:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: invalid new_owner: {exc}")
        if bytes(owner.as_bytes) == b"\x00" * Address.SIZE:
            raise gl.vm.UserError(
                f"{ERR_EXPECTED}: refusing to transfer to the zero address"
            )
        profile.owner = owner

    # -- views --------------------------------------------------------------

    @gl.public.view
    def get_profile(self, profile_id: u256) -> dict:
        profile = self._require_profile(profile_id)
        degraded = int(profile.consecutive_failures) >= FAILURE_DEGRADE_THRESHOLD
        return {
            "owner": str(profile.owner),
            "entity_name": str(profile.entity_name),
            "criteria": str(profile.criteria),
            "min_alert_score": int(profile.min_alert_score),
            "cooldown_seconds": int(profile.cooldown_seconds),
            "active": bool(profile.active),
            "scored": bool(profile.scored),
            "version": int(profile.version),
            "score": int(profile.score),
            "confidence": int(profile.confidence),
            "signals_digest": str(profile.signals_digest),
            "last_assessed_at": str(profile.last_assessed_at),
            "last_change_at": str(profile.last_change_at),
            "consecutive_failures": int(profile.consecutive_failures),
            "total_assessments": int(profile.total_assessments),
            "signal_count": len(profile.signals),
            "source_count": len(profile.sources),
            "subscriber_count": len(profile.subscribers),
            "degraded": degraded,
            "reliable": bool(profile.active) and bool(profile.scored) and not degraded,
        }

    @gl.public.view
    def get_signals(self, profile_id: u256) -> list:
        profile = self._require_profile(profile_id)
        return self._signals_to_list(profile)

    @gl.public.view
    def get_sources(self, profile_id: u256) -> list:
        profile = self._require_profile(profile_id)
        return self._sources_to_list(profile)

    @gl.public.view
    def get_history(self, profile_id: u256) -> list:
        profile = self._require_profile(profile_id)
        return [
            {
                "version": int(r.version),
                "assessed_at": str(r.assessed_at),
                "score": int(r.score),
                "confidence": int(r.confidence),
                "summary": str(r.summary),
                "changes": json.loads(str(r.diff_json)) if r.diff_json else [],
            }
            for r in profile.history
        ]

    @gl.public.view
    def get_latest_assessment(self, profile_id: u256) -> dict | None:
        profile = self._require_profile(profile_id)
        if len(profile.history) == 0:
            return None
        record = profile.history[len(profile.history) - 1]
        return {
            "version": int(record.version),
            "assessed_at": str(record.assessed_at),
            "score": int(record.score),
            "confidence": int(record.confidence),
            "summary": str(record.summary),
            "changes": json.loads(str(record.diff_json)) if record.diff_json else [],
        }

    @gl.public.view
    def get_subscribers(self, profile_id: u256) -> list:
        profile = self._require_profile(profile_id)
        return [
            {
                "subscriber": str(e.subscriber),
                "alert_below": int(e.alert_below),
            }
            for e in profile.subscribers
        ]

    @gl.public.view
    def is_due(self, profile_id: u256) -> bool:
        profile = self._require_profile(profile_id)
        if not profile.active:
            return False
        return self._cooldown_remaining(profile, current_datetime()) == 0

    @gl.public.view
    def profile_count(self) -> int:
        return int(self.next_id) - 1
