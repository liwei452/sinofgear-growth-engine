# Factory-owner growth workspace design

Date: 2026-08-14
Status: approved by the supplied UI concept and delegation corrections

## Product boundary

This repository is the only implementation target. The independent site is a future URL/UTM destination only. The MVP does not upload or interpret drawings, build engineering RFQs, quote, send messages, publish to social networks, request OAuth credentials, or scrape LinkedIn.

The product distinguishes four objects: target account, contact, intent signal, and inbound lead. Public or licensed source evidence must remain attached to every discovered opportunity. Built-in examples must say `Demo / Fake` and must never look like live discoveries.

## Ordinary-user information architecture

The left navigation contains exactly five entries: `今天`, `推广`, `客户机会`, `效果`, and `我的公司`. Internal objects such as Campaign, Prompt, Provider, Job, SourceSignal, connector credentials, and publishing tasks stay out of ordinary-user pages. Existing advanced capabilities remain available only through an administrator boundary.

The `今天` page uses the approved two-column concept:

- Left: today's purchase opportunities with company, country, industry/size, demand summary, signal source, discovery time, intent tier, evidence status, and actions `加入跟进`, `生成联系草稿`, and `查看证据`.
- Right: explainable AI brand/search visibility; `AI 已知道 / 还不清楚 / 建议补充`; and channel performance for LinkedIn, Facebook, Instagram, TikTok, with YouTube optional.

Mobile order is opportunities, AI knowledge/visibility, then channels. Cards replace wide tables. All interactive controls are keyboard reachable and at least 44px high.

## Core workflows

`推广` starts with confirmed company/product facts and an optional goal. AI proposes an ICP, source strategy, bilingual content plan, and channel packages. A human reviews the plan and content before anything can leave the system.

TikTok is first-class. Its manual publishing package includes a 15–60 second script, shot list, English voiceover, Chinese subtitles, 9:16 requirements, title, hashtags, CTA, UTM, planned date, publication result, and metric backfill. LinkedIn Company Page, Facebook Page, and Instagram Business receive channel-appropriate manual packages. A Fake Connector demonstrates readiness without making an external request.

`客户机会` shows evidence-backed target accounts separately from their contacts and intent signals. `加入跟进` creates a lightweight follow-up item; CRM is only an optional later export. `生成联系草稿` produces English copy and a complete Chinese explanation, never a sent message.

`效果` records channel, UTM clicks, replies, inbound inquiries, and manually backfilled publication metrics. It shows numerator, denominator, time range, and evidence, and explains low-sample uncertainty.

`我的公司` presents confirmed facts, uncertain facts, and suggested additions with field source, verification state, updated time, and estimated source cost.

## Connector and safety boundary

Every platform connector exposes capabilities and readiness. Real connectors without approved OAuth/scopes remain `CONFIGURATION_REQUIRED`. The Fake Connector can only create previews/manual publishing packages and simulated metric receipts. No password, cookie, verification code, or private-message automation is accepted.

## Visual system

Use a white canvas, restrained accessible blue, dark neutral text, subtle borders, small radii, and light shadows. Preserve the approved concept's information density and hierarchy. Avoid AI-purple gradients, oversized marketing typography, unexplained scores, emoji-only icons, and decorative motion. Visibility scores always expose their evidence and missing-evidence explanation.

## Acceptance slice

The local MVP passes when a user can open the five-entry workspace, inspect clearly labeled demo evidence, add an opportunity to follow-up, generate a bilingual contact draft, review a multi-channel plan including a complete TikTok package, and inspect explainable channel/visibility metrics without any real external side effect.
