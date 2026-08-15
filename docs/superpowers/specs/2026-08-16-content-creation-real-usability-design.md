# Content Creation Real Usability Design

## Outcome

The ordinary content path becomes one evidence-backed AI workflow: AI evaluates the verified product, market, buyer profile, objective and selected channels, then produces one publication language and genuinely different channel variants. Chinese is optional internal reference only and is never copied into a publishable channel payload unless Chinese is the selected publication language.

This slice does not redesign the five main pages, generate video, publish to a real platform, authorize an account, or change the independent website.

## Confirmed problems

- The frozen generation snapshot already contains `language`, `customer_type`, `content_objective`, `landing_page_url`, `prohibited_claims`, selling points, advantages and verified facts, but the prompt renderer omits most of them.
- `PlatformContent` currently copies the approved master title/body/CTA and adds only `platform_code`.
- TikTok package preparation hard-codes 30 seconds, an empty shot list, English voiceover and a Chinese placeholder subtitle.
- The content payload cannot express publication language, hashtags, evidence references, landing page, or TikTok structure.
- The page exposes both the AI recommendation path and the legacy manual four-step creation wizard as competing primary paths.

## Chosen approach

Use one audited `CONTENT_GENERATE` AI run to produce a versioned master payload plus one structured variant for every platform selected by the approved brief. `PlatformContent` remains a separate human-review record, but it is created from its exact generated variant instead of copying the master body.

This is preferred over synchronous per-platform AI calls because it preserves one immutable input snapshot, one costed AI run, deterministic evidence lineage and the existing approval model. It is preferred over a new campaign/agent subsystem because the current brief, job, AI run, content revision and review models already provide the required boundaries.

## Generation input and prompt

The prompt renderer serializes a bounded, scrubbed generation snapshot after a fixed instruction. The model receives:

- target publication language;
- target country and buyer/customer type;
- content objective and CTA;
- landing page URL;
- selected products, platforms and safe asset metadata;
- verified product facts with evidence identifiers;
- selling points, advantages, keywords and prohibited claims;
- approved ontology concepts.

The instruction states that every publishable string must use the single target language, prohibited claims must not appear, unsupported facts must not be invented, and each platform needs a materially adapted version. Prompt input is untrusted data and cannot alter the JSON schema or human-review requirement.

## Versioned payloads

Legacy version-1 payloads remain readable so existing approved history does not disappear. Newly generated payloads use `schema_version: 2`.

The version-2 master payload contains:

- `language`, `title`, `body`, `cta`, `landing_page_url`;
- `concept_codes` and `evidence_fact_ids`;
- optional `internal_translation_zh` for reviewer comprehension only;
- `platform_variants`, exactly one for each selected platform.

Every platform variant contains `platform_code`, the same `language`, adapted `title`, `body`, `cta`, `landing_page_url`, `hashtags`, and `evidence_fact_ids`. Platform codes and fact identifiers must exactly match the frozen brief/snapshot allow-lists.

TikTok additionally requires:

- `duration_seconds` from 15 through 60;
- `aspect_ratio` fixed to `9:16`;
- a target-language `script`, `voiceover`, and `subtitles`;
- `voiceover_language` and `subtitle_language` equal to the publication language;
- a non-empty bounded `shot_list` with scene, visual direction and on-screen text.

No internal Chinese translation is copied into `PlatformContent` or a channel package.

## Channel adaptation

`create_platform_content` selects the platform's exact variant from the approved current master payload. Missing, duplicate or wrong-platform variants fail closed. LinkedIn, Facebook, Instagram and TikTok therefore receive independent AI-written structures while inheriting the same verified fact references and immutable master provenance.

For legacy master content, existing platform records remain viewable. Creating a new channel variant from a legacy master is blocked with a plain recovery instruction to regenerate from the current brief, preventing the old copy behavior from continuing.

## TikTok publishing preparation

Channel package preparation copies the reviewed TikTok duration, script, shot list, voiceover, subtitles, hashtags, language, CTA and landing URL from the approved `PlatformContent`. It no longer fabricates a 30-second duration, empty scenes, English voiceover, or Chinese placeholder. Package creation remains local and review-only; it performs no platform call.

## Ordinary user path

The content factory presents one primary creation action: AI recommends evidence-backed product/market/buyer/language directions, the user selects one, AI generates the complete multi-channel set, and the result opens for review. The legacy manual wizard is removed from the ordinary creation surface. Existing briefs, jobs, revisions, archives and generated results remain visible for audit and recovery.

## Failure behavior

- Missing verified facts, target language, selected platform, current prompt, or provider configuration stops before a request.
- Schema mismatch, unknown platform/fact, language mismatch, invalid TikTok duration, empty shot list, or prohibited extra field fails the AI run without creating content.
- Real-provider failure never falls back to Fake and never reports success.
- Existing content, evidence and review history are never deleted.

## Acceptance tests

- Prompt rendering proves all business constraints and the complete frozen input reach the provider.
- Output validation rejects a second publication language, unknown fact IDs, missing/duplicate platforms, and malformed TikTok structures.
- Four selected platforms create four distinct reviewable payloads from one approved master.
- TikTok package fields equal the approved TikTok variant and contain no fixed placeholder copy.
- Chinese internal reference never appears in publishable payloads for a non-Chinese target language.
- The content factory exposes the AI path as the only ordinary creation path and still shows generated output/evidence/review actions.
- Organization isolation, idempotency, legacy readability and manual approval remain green.

