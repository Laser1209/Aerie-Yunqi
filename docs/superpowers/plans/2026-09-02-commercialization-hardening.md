# Commercialization Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the repaired Aerie core into a legally safer, testable commercial pilot without binding the product to the private Ita/Yunqi persona.

**Architecture:** Keep the local-first core and expose integrations through adapters. A clean installation gets a neutral built-in persona; existing user data remains private and is migrated without overwriting it. Companion Studio is an optional same-machine HTTP presentation adapter. Billing and ads are attached to confirmed subscription/trial boundaries and remain non-blocking.

**Tech Stack:** Python 3.14/FastAPI, Electron 28/electron-builder 24, SQLite, Companion Studio aiohttp, OpenAI Ads Pixel/CAPI, existing Node/Python tests.

## Global Constraints

- Never include the private Ita/Yunqi persona, its relationship story, intimate traits, or seed memories in the commercial default.
- Never collect chat text, raw audio, screen captures, API keys, or persona private fields for advertising.
- Free tier must work without a paid external model; provider/API costs must never be silently billed to users.
- All payment and conversion reporting failures are non-blocking and must not alter the core chat result.
- Companion Studio remains optional; Aerie remains the source of truth for conversation and identity.

### Task 1: Separate commercial default persona from private persona data

**Files:**
- Create: `core/persona_hub/preset_templates/aerie_default.json`
- Modify: `core/persona_hub/persona_manager.py`
- Modify: `config/persona_loader.py`, `config/persona.yaml`
- Modify: `electron/src/renderer/index.html`, `electron/src/renderer/js/chat.js`, `electron/src/renderer/js/settings.js`
- Test: persona manager and persona API tests

**Interfaces:**
- `AERIE_DEFAULT_PERSONA_ID` selects the built-in template id, defaulting to `aerie_default` for clean installs.
- Existing `data/personas/yita_default.json` remains untouched and loadable as a user-private legacy persona.

- [ ] Add a neutral template with no romance, sexualized body measurements, ownership language, or real-person backstory.
- [ ] Make built-in fallback and reset logic use the selected default id and `is_builtin`, not a hard-coded Ita id.
- [ ] Keep legacy Ita records available only when present in the user data directory; do not seed them into a new profile.
- [ ] Replace visible hard-coded default labels/placeholders with the active persona name or `Aerie Companion`.
- [ ] Test a clean temporary profile and a profile containing legacy Ita data; assert no cross-profile overwrite.

### Task 2: Make the desktop release reproducible

**Files:**
- Modify: `electron/electron-builder.yml`, `electron/package.json`
- Modify: `scripts/build_python_runtime.py`
- Create: `scripts/write_build_manifest.py`
- Test: package inspection script and clean-profile launch smoke

**Interfaces:**
- `npm.cmd run build:win` produces NSIS and portable artifacts with a manifest containing git commit, package version, runtime hash and build timestamp.

- [ ] Use one builder config source and valid locale ids `zh_CN` and `en_US`.
- [ ] Make runtime rebuild fail with a precise locked-file message and support an alternate output directory for retry.
- [x] Write the manifest inside the packaged resources and expose only non-sensitive fields through `/api/health`.
- [x] Build on a clean output directory, inspect `app.asar`, and launch the unpacked app with an isolated data directory.

### Task 3: Add the Companion Studio presentation adapter

**Files:**
- Create: `core/companion_studio_adapter.py`
- Modify: `core/companion.py`, `core/api_server.py`
- Modify: `E:/Retrieval-based-Voice-Conversion-WebUI/companion-studio/backend/app/config.py` only if a documented CORS/origin contract is required
- Test: adapter contract tests and Companion Studio backend tests

**Interfaces:**
- `CompanionStudioAdapter.speak(text, voice_config) -> {audio_url, duration_ms, provider}` with bounded timeout and disabled fallback.
- `GET /api/integrations/companion-studio` reports reachable/configured/disabled without exposing tokens or local absolute paths.

- [ ] Keep Aerie chat and persistence authoritative; send only approved reply text to Studio.
- [ ] Support Studio `disabled` mode and missing Live2D/RVC assets without failing chat.
- [ ] Verify `/api/talk`, `/api/speak`, `/api/models/live2d`, `/api/models/rvc` against the existing 6-test Studio backend baseline.
- [ ] Add an opt-in UI toggle and an explicit status/error message.

### Task 4: Define pricing and metering without surprise API bills

**Files:**
- Create: `docs/commercialization/pricing-policy.md`
- Create: `core/entitlement_service.py`
- Modify: `core/api_server.py`, `electron/src/renderer/js/settings.js`
- Test: entitlement and provider-budget tests

**Interfaces:**
- `EntitlementService.plan_for(user_id) -> {plan, features, limits}`.
- `EntitlementService.can_use(feature, estimated_provider_cost) -> {allowed, reason}`.

- [ ] Free: local chat, basic memory, one persona, one workspace, no hosted inference subsidy.
- [ ] Pro: multi-persona, advanced workspace recipes, proactive scheduling, Studio connectors and sync entitlement; hosted API usage is metered separately.
- [ ] Charge software subscription for product features; charge hosted model/voice usage at cost-plus transparent metered rates, or require the user’s own API key.
- [ ] Show provider name, estimated cost, monthly usage and hard limit before paid calls; never auto-upgrade or silently consume a platform key.
- [ ] Keep payment provider implementation behind an adapter until a confirmed vendor and jurisdiction are selected.

### Task 5: Instrument confirmed conversion boundaries

**Files:**
- Create: `analytics/openai_ads_pixel.js` (browser-only helper)
- Create: `server/openai_ads_capi.py` (server-only helper)
- Modify: confirmed registration/trial/subscription success handlers only
- Test: secret exposure, dedupe, consent and source URL tests

**Interfaces:**
- `track_pixel(event_name, event_id, options)` never throws.
- `send_capi_event(event_name, event_id, request_context)` is bounded, server-only and never blocks the success response.

- [ ] Use only documented supported event names and one shared pixel id/event id for paired Pixel+CAPI events.
- [ ] Respect consent/opt-out and sanitize `source_url`; pass opaque `oppref` unchanged when available.
- [ ] Do not instrument page views or clicks until the marketing surface and success semantics are confirmed.
- [ ] Run the Ads verification helpers and a repository scan proving no CAPI secret appears client-side.

### Task 6: Pilot launch and competitive advantage validation

**Files:**
- Create: `docs/commercialization/pilot-experiment.md`
- Modify: `docs/commercialization/2026-09-02-aerie-market-launch-plan.md`
- Test: release smoke checklist and manual Windows runbook

**Interfaces:**
- Pilot report records cohort, build manifest, funnel events, support incidents, cost per activated user and opt-out/deletion handling.

- [ ] Run a 10-20 user closed beta before paid ads.
- [ ] Compare privacy, executable workflow and replaceable-persona messages with equal budgets.
- [ ] Gate public ad spend on install success >=90%, first-message completion >=80%, crash rate <2% and no unresolved P0/P1 data/privacy issue.
- [ ] Review competitor claims and license terms quarterly; do not copy proprietary assets or unsupported performance claims.

## Pricing Recommendation

Start with a **free local core + Pro software subscription + transparent hosted usage** model. The subscription pays for product capabilities (persona management, workflow recipes, proactive automation, Studio connectors, updates and support). Hosted LLM/ASR/TTS/RVC calls are either user-supplied keys or separately metered pass-through usage with a visible ceiling. This protects margin, preserves the local-first promise and avoids making API consumption an invisible recurring fee.
