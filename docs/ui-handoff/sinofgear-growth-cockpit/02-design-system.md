# 02 Design System

## Visual direction

Use the supplied reference image for hierarchy and composition, not for its fake opportunity names, scores, graphs, avatar, dates, or numbers. Reproduce the visual language only.

## Color tokens

| Token | Value | Use |
|---|---:|---|
| Primary | `#1268E3` | Primary actions, active navigation, selected state |
| Primary hover | `#0B56C5` | Hover/pressed primary |
| Primary soft | `#EAF2FF` | Active navigation background, selected panels |
| Canvas | `#F6F8FB` | Application background |
| Surface | `#FFFFFF` | Panels, cards, drawers |
| Strong text | `#172235` | Headings and primary body text |
| Muted text | `#667386` | Secondary text and metadata |
| Border | `#DDE4ED` | Panel and control borders |
| Success | `#18875D` | Verified/success status with text/icon |
| Success soft | `#EAF8F1` | Success badge background |
| Warning | `#B86B00` | Warning text/icon |
| Warning soft | `#FFF6E7` | Warning badge/background |
| Destructive | `#B83243` | Reversible archive/destructive controls |
| Focus | `#0B56C5` | Visible keyboard focus ring |

Functional state must never rely on color alone.

## Typography

- Latin and numerals: Inter.
- Chinese fallback: PingFang SC, Microsoft YaHei, system sans-serif.
- Body: 14px desktop, 16px mobile, line-height about 1.5.
- Labels/meta: 12px only when nonessential and high contrast.
- Card title: 16–20px, weight 600.
- Page title: 28px, weight 650–700.
- Data values: tabular numerals.
- Avoid serif fonts, playful display fonts, and all-caps eyebrow text except short technical labels.

## Shape and spacing

- Spacing scale: 4, 8, 12, 16, 20, 24, 32px.
- Control radius: 8px.
- Panel/card radius: 12px.
- Status/filter pill: full radius.
- Desktop sidebar: 216–224px.
- Main content maximum: about 1440px with responsive gutters.
- Primary touch/click targets: at least 44×44px where practical.

## Elevation

- Use borders for normal separation.
- Use subtle shadow only for drawers, menus, modals, and the primary Today dashboard surfaces.
- Do not apply the same shadow to every card.

## Icons

- One SVG outline family only: Lucide-style preferred.
- Standard navigation size: 20px; action size: 18–20px.
- Suggested concepts: Today/house, Promotion/send, Opportunities/users or target, Results/chart, Company/building, Settings/settings, Help/circle-help.
- No emoji, text initials, mixed filled/outline families, or guessed platform logos.
- Use official LinkedIn, Meta, Instagram, TikTok, and YouTube brand assets where brand marks are shown.

## Motion

- Subtle only: 150–250ms.
- Use opacity/transform, not width/height animation.
- Drawers slide from the relevant edge; content replacement crossfades.
- No decorative scroll reveal requirement.
- Respect `prefers-reduced-motion`.

## Breakpoints

- 375px: phone acceptance.
- 768px: tablet acceptance.
- 860px: desktop sidebar becomes mobile drawer below this width.
- 1024px: compact desktop acceptance.
- 1440px: wide desktop acceptance.

