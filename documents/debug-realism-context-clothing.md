# Debug Session: Realism Context Clothing

Status: [OPEN]
Session: realism-context-clothing

## Symptom

The generated image prompt is insufficiently photorealistic, contains physically inconsistent visual details, and uses clothing that does not match the ongoing conversation context.

## Hypotheses

- H1: The base prompt lacks executable photographic realism constraints beyond generic wording.
- H2: Time, solar-light, room, and subject details are concatenated without a consistency pass.
- H3: Clothing is hard-coded in the role template and is not derived from conversation context.
- H4: World context is appended after the base prompt and cannot correct conflicting fixed scene or clothing details.

## Evidence

- Production timeline `169-175` shows only generic realism wording, a hard-coded loose home T-shirt, and duplicated `窗外是窗下是` light text.
- The image candidate previously carried only the current `user_raw`; no recent conversation context reached the prompt resolver.
- The close-up base only referenced appearance, with no body-proportion, skeleton, joint-range, or camera ergonomics constraints.

## Fix

- Recent user/assistant messages are reduced to a bounded `conversation_context` and propagated through pipeline, sidecar storage, event reconstruction, and prompt resolution.
- Semantic photo analysis now extracts an explicit `outfit`; deterministic fallback extracts the latest clothing sentence without inventing clothes.
- Prompts now include executable phone-photo realism, skin/fabric texture, optical, light, gravity, anatomy, body-proportion, skeleton, muscle-line, joint-range, and limb-consistency constraints.
- Legs, feet, waist, and child focuses use a self-held rear-camera composition; face, hair, and shoulder-neck focuses keep front-camera selfie composition.
- Solar room-light text strips duplicated outside prefixes and explicitly forbids direct sunlight when the sun is below the horizon.

## Verification

- Targeted regression: 65 tests passed.
- End-to-end prompt contract passed through sidecar serialization → event reconstruction → real prompt resolver.
- Verified output contains conversation-matched shorts, socks, and slippers; rear-camera leg composition; realistic anatomy constraints; and excludes the hard-coded T-shirt, front camera, first-person clothing wording, duplicated outside prefix, and duplicate punctuation.
- Diagnostics are clean for companion, pipeline, solar-time, consumer, and sidecar files.
