# Product Requirements Document
## 15 Signals — Inner State Intelligence Through Daily Writing

**Version:** 0.1 (Internal Discussion Draft)
**Author:** Product
**Date:** 2026-04-28
**Status:** Pre-alignment

---

## Assumptions

Before proceeding, the following assumptions are made where the product definition left room for interpretation. These should be validated by the team before the PRD is finalized.

1. **Signal definition is fixed for V1.** The 15 spiritual signals are a closed, internally defined taxonomy. Users do not see the signal names by default — they see translated, human-readable interpretations.
2. **Journal entries are text-only in V1.** Voice, images, and other media are out of scope.
3. **The product is English-first.** Internationalization is a future concern.
4. **Signal detection is LLM-based.** The system uses a large language model to score entries against each of the 15 signals. No custom ML model is required for V1.
5. **"Trend" means change over time, not single-session score.** A signal is considered "strengthening" when its scored intensity increases consistently across multiple days, not when it spikes once.
6. **The thinker library is curated and static in V1.** The 40+ thinker–signal mappings are authored by the team, not generated dynamically.
7. **The product is a mobile-first web app in V1.** Native app is a future decision.
8. **Users write one entry per day by default.** Multiple entries per day are allowed but treated as a single daily session for scoring purposes.
9. **There is no social or sharing layer in V1.** This is a private, single-user experience.
10. **"Prominent signal" means the top 1–3 signals with the strongest upward trend over the most recent 7–14 days**, not the highest absolute score on any given day.

---

## 1. One-Sentence Product Definition

**15 Signals** is a daily journaling product that detects which of 15 core psychological and existential signals are growing stronger in a user's writing over time, and surfaces insights drawn from the world's leading thinkers to help users understand and navigate their inner condition.

---

## 2. Product Vision and Value Proposition

### Vision

Most people who journal do so without feedback. They write, they feel some relief, and then they close the notebook. The writing disappears into silence. Over time, they may not notice that the same fears, the same restlessness, or the same sense of meaninglessness has been quietly intensifying — because no one, including themselves, has been paying close enough attention.

15 Signals is built on a single conviction: **the pattern in your writing knows something you don't yet consciously know about yourself.** The product's job is to surface that pattern, name it with precision, and connect it to a body of thought that gives the user a richer frame for understanding what is happening inside them.

The ambition is not to fix the user. It is to help them *see* — with more resolution, more continuity, and more intellectual substance than they could manage alone.

### Value Proposition

| For whom | Value delivered |
|---|---|
| The user | A feedback loop on their inner life that is honest, non-clinical, and intellectually serious |
| The product | Defensible differentiation through the combination of signal detection + thinker library, which no generic journaling or AI chat app replicates |
| The ecosystem | A bridge between the rich tradition of humanistic thought and the everyday experience of writing about one's life |

### The Core Promise

> "Write a few lines every day. We will show you what is quietly shifting in you — and what some of the most serious thinkers in history said about exactly that."

---

## 3. Target User Personas

### Persona A — The Reflective Professional (Primary)

- **Age:** 28–45
- **Context:** Knowledge worker, moderately high stress, some prior engagement with self-help, therapy, or philosophy
- **Current behavior:** Journals intermittently, reads non-fiction, listens to podcasts about psychology or ideas
- **Pain point:** Journals without knowing if anything is accumulating or changing. Feels vaguely that something is off but cannot name it precisely.
- **What they want from this product:** To feel that their writing is going somewhere — that someone (or something) is actually reading it and giving them back something meaningful
- **Retention driver:** The sense that the feedback is getting more accurate and more relevant the more they write

### Persona B — The Philosophically Curious Explorer (Secondary)

- **Age:** 22–35
- **Context:** Student, early-career, or career-changer; drawn to ideas, meaning, and self-understanding
- **Current behavior:** Reads philosophy or social theory, keeps a sporadic journal, fascinated by frameworks for understanding human experience
- **Pain point:** Disconnected from practical tools that engage with the depth of thought they care about
- **What they want:** A product that takes ideas seriously and connects them to their actual life, not a simplified wellness dashboard
- **Retention driver:** The thinker library — they will return to explore perspectives and deepen their reading

### Persona C — The Quiet Observer (Tertiary)

- **Age:** 35–60
- **Context:** Going through a significant life transition (career change, grief, relationship shift, identity renegotiation)
- **Current behavior:** Unlikely to seek formal therapy, but genuinely wants to understand what is happening in them
- **Pain point:** No appropriate tool exists that is serious but not clinical
- **What they want:** A private space with real feedback that does not feel like a mental health app
- **Retention driver:** The trend view — watching signals shift over weeks gives them a sense of agency and movement

---

## 4. Why Users Would Keep Coming Back

Retention in this product depends on three interlocking mechanisms:

**1. Accumulation Value**
The product gets meaningfully better the more a user writes. A single entry produces thin signal. Ten entries across two weeks produce a recognizable trend. Thirty entries begin to reveal a genuine pattern. Users who understand this will return because their investment compounds.

**2. The Feedback Loop is Delayed by Design**
The most useful feedback — trend-based signal highlighting — requires at least 5–7 days of data. This creates a healthy pull: users return to see whether the signal that appeared last week is strengthening or softening. This is fundamentally different from an instant-gratification loop.

**3. Intellectual Curiosity as a Pull**
The thinker library is not a reference document — it is an invitation. When a user sees that what they are experiencing connects to, say, Kierkegaard's writing on anxiety or Hirschman's work on loyalty and exit, they are not just validated. They are provoked. They want to know more. This creates a content pull that most productivity apps entirely lack.

**4. The Signal Highlight Changes Over Time**
Because the product highlights only the top 1–3 strengthening signals, the featured content changes as the user's inner state evolves. The product does not feel repetitive because the lens it offers tracks the user's actual movement.

**5. Low Friction Entry Point**
A daily journal entry can be two sentences. The product does not demand depth — it extracts depth. This low entry cost makes daily return easy.

---

## 5. Core Usage Scenarios

### Scenario 1 — The Quick Daily Check-in
A user opens the app during their commute or before bed. They write 3–5 sentences about how the day felt. The system accepts the entry, confirms it has been logged, and shows a brief reflection drawn from the most recent trend analysis. The session takes under three minutes.

### Scenario 2 — The Weekly Signal Review
After a week of entries, a user opens the trend view. They see that one or two signals have been flagging consistently. The system surfaces a short interpretation of what that pattern suggests, followed by an optional expansion into the relevant thinker perspectives. The user reads, reflects, and possibly writes a longer entry in response.

### Scenario 3 — The Thinker Dive
A user notices that their feedback consistently references ideas related to exit, loyalty, and voice (a signal cluster). Curious, they tap through to see which thinker is associated with this cluster. They find Hirschman. They read the associated excerpt and a short editorial framing how his model applies to their situation. They bookmark it and return to it later.

### Scenario 4 — The Long-Arc Review
After 30–60 days, a user opens the monthly view. They can see which signals dominated the first two weeks, which faded, and which are newly emerging. This longitudinal view gives them a genuine sense of movement in their inner state — a kind of personal evidence that things are changing, even when change feels invisible from day to day.

---

## 6. The User Journey

### A Single Day

| Time | User action | System response |
|---|---|---|
| Morning or evening | Opens app | Greeted with a minimal, calm prompt — not a blank box |
| Writes entry | Types 2–10 sentences freely | System accepts, scores silently in background |
| After submission | Views today's reflection | Short interpretive text based on accumulated trend (not just today's entry) |
| Optional | Taps to expand thinker context | System reveals the theoretical frame and relevant thinker |
| Closes app | Session ends | System updates trend model |

### Across a Week

- **Days 1–2:** Entry accepted; feedback is intentionally minimal ("still building your picture")
- **Day 3–4:** First tentative signal identification appears; the system begins offering light interpretive feedback
- **Day 5–7:** At least one signal trend emerges; the weekly reflection is activated with full thinker context
- **End of week:** User receives a short "week in review" — 2–3 sentences on what the week's writing revealed, plus the dominant signal and its associated thinker

### Across a Month

- **Week 1:** Baseline establishing
- **Week 2:** First meaningful trends visible; user begins to recognize the feedback as accurate
- **Week 3:** User notices that the signal is shifting — either deepening or softening — depending on what they have been writing
- **Week 4:** Monthly reflection unlocks; a narrative summary of the month's signal arc, written in plain language, with a note on what persisted and what changed
- **After 30 days:** The product has enough data to begin distinguishing between chronic signals (persistent patterns) and acute signals (temporary spikes), and adjusts its framing accordingly

---

## 7. The Core Product Mechanism

The product's logic operates across four layers:

```
Layer 1: Raw Input
  └─ Daily journal entry (free-form text)

Layer 2: Signal Scoring
  └─ LLM scores the entry against 15 signal dimensions
  └─ Scores are stored per entry, per signal, on a normalized scale

Layer 3: Trend Detection
  └─ For each signal, the system calculates a trend slope over a rolling window (7 or 14 days)
  └─ Signals with upward trend slope above a threshold are flagged as "strengthening"
  └─ The top 1–3 signals by trend intensity become the "active signals" for this user

Layer 4: Interpretation and Intervention
  └─ Active signals are matched to thinker mappings
  └─ System generates interpretive feedback, referencing the thinker's framework
  └─ User sees plain-language reflection; thinker details are expandable, not default
```

This layered architecture ensures that the user experience feels personal and intelligent, while the underlying mechanism is systematic and reproducible.

---

## 8. How the System Detects Strengthening Signal Trends

### The Scoring Step

Each journal entry is analyzed by the LLM using a structured scoring prompt that evaluates the text against each of the 15 signals. The prompt is carefully designed to:

- Assess intensity, not just presence (a signal can be faintly present or strongly dominant)
- Distinguish between the user describing a past event versus expressing a present emotional or existential state
- Weight emotional texture, word choice, and thematic preoccupation — not just explicit statements

Each signal receives a score from 0–10 per entry. These scores are stored.

### The Trend Calculation Step

Signal trend is calculated as the slope of the score series over a rolling 7-day and 14-day window. A signal is considered "strengthening" when:

1. Its 7-day slope is positive (scores are rising)
2. It has appeared in at least 3 of the last 7 days with a score above a minimum threshold (i.e., it is consistent, not a one-day spike)
3. Its intensity is above the user's own historical median for that signal (personalized baseline)

This personal-baseline comparison is critical: the product is not measuring the user against a population norm. It is measuring the user against their own prior self.

### Why Rolling Windows, Not Single Sessions

A single entry can be distorted by a bad day, a specific incident, or the user's writing mood. The trend model smooths this out. A signal that scores high once but does not persist is not flagged. A signal that steadily intensifies over ten days — even if individual scores are moderate — is treated as more significant than a single high-score spike.

### The Output

The trend engine produces a ranked list of signals sorted by trend strength. The top 1–3 become the user's "active signals" for the current period. The rest are held in the background — stored but not surfaced.

---

## 9. Why the Final Experience Highlights Only the Top Signals

Showing all 15 signals at once would be the wrong product decision for three reasons:

**1. Cognitive overload undermines self-reflection.**
If a user sees that they scored positively on 8 signals today, they have no idea where to focus. The signal-to-noise ratio drops to zero. The product becomes a dashboard of abstract metrics with no clear meaning.

**2. Most signals are always present at low levels. Only a few are truly moving.**
Just as a doctor does not list every possible diagnosis — they identify what is *changing* and *clinically significant* — this product should direct attention to what is *trending*, not everything detectable. The 15 signals are not exclusive categories; many overlap. The user is always expressing multiple signals simultaneously. Highlighting what is strengthening is the only way to make that data actionable.

**3. Highlighting 1–3 signals creates a story, not a spreadsheet.**
When a user sees that two related signals are both strengthening simultaneously, the system can surface a coherent interpretation: "These two patterns together suggest..." That narrative coherence is only possible when the field of view is narrow enough to hold together. Showing 15 parallel scores destroys this coherence.

The principle here is: **the product's job is editorial curation, not data disclosure.**

---

## 10. The Role of the Library of 40+ Thinkers

The thinker library serves three distinct functions:

### Function 1 — Interpretive Authority
When the system tells a user that a signal is strengthening, it must earn the user's trust that the interpretation is substantive, not generic. The thinker library is the foundation of that substance. "What you're describing connects to what Simone Weil called *affliction*" is a fundamentally different kind of feedback than "You may be feeling overwhelmed." The former has intellectual weight. The latter could come from any wellness app.

### Function 2 — Reframing
One of the product's most valuable functions is recontextualization. A user who feels that they are "failing" at something may be experiencing what Albert Hirschman called the moment before *exit* — not failure, but a legitimate response to deteriorating conditions. Reframing a user's experience through a thinker's lens can produce genuine insight, not just validation.

### Function 3 — Opening a Door
Not every user will want to read Hirschman or Weil in full. But some will. The thinker library creates a path from the user's own private experience outward into a broader intellectual tradition. This is a rare affordance. No other consumer product builds this bridge in a systematic, personalized way.

### Curation Principles

The thinker selection should be governed by these principles:
- **Range matters:** The library should span economics, philosophy, theology, sociology, psychoanalysis, and existentialism. It should not be dominated by any single tradition.
- **Relevance, not prestige:** A thinker should be included because their work directly addresses one or more of the 15 signals, not because they are famous.
- **Accessibility:** The editorial framing of each thinker's perspective must be readable by an intelligent non-specialist. Dense academic language is never shown to the user without translation.

---

## 11. The Thinker-to-Signal Mapping in Product Structure

### The Mapping Model

Each of the 15 signals maps to 2–5 thinkers. Each thinker maps back to 1–3 signals. This is a many-to-many relationship, not a one-to-one assignment. The mapping is authored and curated by the product team, not generated algorithmically.

### How the Mapping is Reflected in the UX

When a user's active signal is identified:

1. The system selects the most relevant thinker for that signal in the user's current context. If the signal has been active for multiple days, the system may surface a second thinker on a subsequent day — offering a different angle on the same phenomenon.

2. The thinker's perspective is rendered in two layers:
   - **Surface layer (always visible):** A 2–4 sentence interpretation written in the system's voice, informed by the thinker's framework but not attributed by default.
   - **Depth layer (expandable on tap):** The thinker's name, their specific concept or framework, a short excerpt or paraphrase from their work, and a 2–3 sentence editorial framing explaining why this thinker speaks to this signal.

3. Over time, the system tracks which thinkers the user has seen and introduces new ones when the same signal persists — preventing repetition and rewarding continued engagement.

### The Expert/Thinker Page (Content Architecture)

Each thinker has a profile page with:
- Name, brief biography (2–3 sentences), and intellectual tradition
- The 1–3 signals they are mapped to
- Their core concept(s) relevant to those signals
- A short curated excerpt or paraphrase
- Related entries the user has written that triggered this thinker

This page functions as both a content destination and a personalized reading list. It is generated from the static library but filtered by the user's own signal history — making it feel personal even though the underlying content is shared.

---

## 12. Major Functional Modules

| Module | Description |
|---|---|
| **Journal Engine** | Text input, storage, and session management |
| **Signal Scoring Engine** | LLM-based per-entry scoring against 15 signals |
| **Trend Analysis Engine** | Rolling-window trend calculation and active signal selection |
| **Interpretation Generator** | Produces user-facing reflective text based on active signals and thinker mappings |
| **Thinker Library** | Static curated content database: 40+ thinkers, mapped to signals, with excerpts and editorial framing |
| **User History & Timeline** | Stores all entries, scores, and signal histories; powers trend and monthly views |
| **Notification & Habit Layer** | Gentle daily reminders; weekly and monthly summary triggers |
| **User Profile & Onboarding** | Account creation, onboarding, preferences, and privacy controls |

---

## 13. Page-by-Page Breakdown

### Home Page

**Purpose:** Orient the user and invite today's entry.

**What it shows:**
- A minimal daily prompt — not a question, but a soft invitation (e.g., "What is on your mind today?")
- The current active signal (if enough data exists) rendered as a short phrase, not a clinical label
- A subtle visual indicator of the streak or continuity (e.g., "Day 12") — understated, not gamified
- Quick access to the week's reflection if it is available

**What it does not show:**
- A list of all 15 signals
- Charts or score graphs on the default view
- Any language that implies diagnosis or assessment

**Design principle:** The home page should feel like opening a quiet, intelligent notebook — not a dashboard.

---

### Journal Entry Page

**Purpose:** Receive the user's daily writing with as little friction as possible.

**What it shows:**
- A clean, full-screen text input area
- A minimal character/word count indicator (optional, user-settable)
- The date
- A single submit action

**What it does not show:**
- Prompts or questions by default (these can be enabled as an optional setting for users who want them)
- Any real-time signal scoring or feedback — the system should feel like it listens, not like it monitors in real time
- Editing history (entries are intentionally treated as daily snapshots, not living documents)

**After submission:**
- Brief confirmation: "Added."
- Transition to the Feedback Page (see below)

**Design principle:** The entry experience should feel private, unhurried, and free. Nothing about it should feel like filling out a form.

---

### Feedback Page

**Purpose:** Deliver the system's interpretation of the current signal trend.

**What it shows:**
- A short interpretive paragraph (3–6 sentences) written in warm, intellectually serious prose
- This paragraph reflects the user's recent pattern, not just today's entry
- If a thinker perspective is relevant: a teaser line (e.g., "This connects to something Simone Weil observed about attention and suffering")
- A "Read more" expansion that reveals the full thinker context (depth layer)
- On days 1–4 when trend data is sparse: a shorter, more present-tense reflection acknowledging that the picture is still forming

**What it does not show:**
- Signal names in clinical or technical form
- Numerical scores
- All 15 signals
- Generic affirmations ("Great job writing today!")

**Design principle:** The feedback page is the product's most important surface. It should feel like receiving a letter from an intelligent, thoughtful reader — not reading a report.

---

### Trend Page

**Purpose:** Show the user their signal arc over time in a comprehensible, non-overwhelming way.

**What it shows:**
- The 1–3 active signals over the past 7 and 30 days, rendered as a simple visual arc (rising, stable, softening) — not a precise line graph by default
- A brief editorial label for each signal arc (e.g., "This pattern has been intensifying" or "This signal peaked last week and appears to be softening")
- The ability to tap a signal arc and see the entries that contributed most strongly to it
- A monthly narrative summary (unlocks after 30 days)

**What it does not show:**
- All 15 signals in parallel
- Raw score numbers by default
- Comparison to other users

**Design principle:** The trend page should convey movement and change, not surveillance. Users should feel they are understanding themselves over time, not being measured against a standard.

---

### Expert (Thinker) Page

**Purpose:** Allow the user to explore the intellectual frameworks behind their signal feedback.

**What it shows:**
- A personalized view of the thinkers the user has encountered, organized by the signals they address
- Each thinker card: name, tradition, core concept, excerpt, and link to the user's entries that surfaced this thinker
- Thinkers the user has not yet encountered, surfaced based on their signal history, available as an exploratory layer

**What it does not show:**
- The full library of 40+ thinkers in an undifferentiated list
- Academic bibliographies or footnotes
- Thinkers unrelated to the user's signal history (unless the user actively chooses to explore)

**Design principle:** This page should feel like a personalized reading list that the product compiled from your own inner life — not a Wikipedia browsing experience.

---

## 14. MVP Scope

The MVP is the minimum functional version that can validate the product's core hypothesis: **that users will find genuine value in the combination of daily journaling + signal trend detection + thinker-based feedback, and will return to the product consistently over 2–4 weeks.**

### MVP Includes

- Journal entry input and storage
- Signal scoring per entry (LLM-based, against all 15 signals)
- Trend calculation (7-day rolling window, top 1–2 active signals)
- Feedback page with interpretive text (system-generated, informed by thinker mappings)
- Thinker depth layer (expandable) for at least 10 thinkers covering all 15 signals
- Home page and journal entry page
- Basic user account and data persistence
- Daily reminder notification (single, user-configurable time)
- 7-day review trigger (auto-generated after first full week of entries)
- Mobile-responsive web app

### MVP Excludes

- Monthly narrative summary (requires 30+ days of data and more editorial tooling)
- Full thinker library (40+ thinkers) — 10–15 thinkers covering all signals is sufficient for MVP
- Trend visualization page (the trend is surfaced through text, not charts, in MVP)
- Expert/Thinker browsing page (thinkers are surfaced through feedback only in MVP, not navigable)
- Onboarding personalization beyond basic account setup
- Any social or sharing feature

---

## 15. V1 Must-Haves vs. Deferred

### Must Be in V1 (Post-MVP)

| Feature | Rationale |
|---|---|
| Trend visualization page (simple arc view) | Needed for user retention beyond 2 weeks; users need to see their own arc |
| Full thinker library (40+ thinkers) | Intellectual depth is a core differentiator; gaps in coverage will weaken feedback quality |
| Monthly narrative summary | Critical for 30-day retention; the long arc is a key value proposition |
| Thinker browsing/Expert page | Enables the "intellectual curiosity" retention loop that distinguishes this product |
| Distinction between chronic and acute signals | Prevents false positives from one-off bad days; builds trust in the system's accuracy |
| Basic onboarding explanation of how the product works | Users need to understand the accumulation model or they will churn after day 3 |

### Can Be Deferred Post-V1

| Feature | Rationale for deferral |
|---|---|
| Voice entry | Adds input complexity; text is sufficient to validate the core model |
| Multi-language support | English-first is a valid V1 constraint |
| Export / data download | Useful but not a retention driver |
| Optional journaling prompts | Nice-to-have; the product should work without them |
| Advanced signal configuration or personalization | The 15 signals are fixed in V1; user customization adds complexity without clear demand evidence |
| Partnerships or in-app book purchasing | Monetization extension; not required for product-market fit |
| Web vs. native app decision | The mobile web app will suffice for V1; native app investment should follow retention validation |

---

## 16. Risks, Ethical Boundaries, and Disclaimers

### Product Risks

| Risk | Mitigation |
|---|---|
| Users misinterpret signal trends as clinical diagnosis | Explicit in-product language; mandatory disclaimer on onboarding and feedback page |
| LLM signal scoring is inconsistent across entry styles | Red-team testing across diverse writing styles; human review of edge cases during beta |
| Users in acute distress write entries that the system scores but does not escalate | The product must include a clear, persistent note that it is not a crisis service, with links to appropriate resources |
| Users disengage after 3–5 days before trend data accumulates | Onboarding must set the right expectation: "The product gets more meaningful after a full week" |
| Thinker framing could feel culturally narrow or historically insensitive | Diverse curation of thinkers across geographies and traditions; editorial review of all framing copy |

### Ethical Boundaries

**The product must never:**
- Claim to diagnose, treat, or assess mental health conditions
- Use language that pathologizes normal human experience
- Retain user journal entries for any purpose other than generating feedback for that specific user
- Share or use individual user entries for training data without explicit, informed, granular consent
- Surface thinker perspectives that advocate harmful or regressive views

**The product must always:**
- Make clear that users can delete all their data at any time
- Provide immediate, non-intrusive access to crisis resources if entries suggest acute distress (detected via a separate safety classifier, not the signal scoring engine)
- Present the 15 signals as observational lenses, not clinical categories
- Acknowledge the limits of text-based inference ("This is a reflection on your writing, not a judgment about you")

### Required Disclaimers

The following disclaimer must appear during onboarding and remain accessible from the feedback page at all times:

> "15 Signals is a journaling and reflection tool. It is not a medical, psychological, or therapeutic service. The patterns it identifies are observations about your writing, not evaluations of your mental health. If you are experiencing distress, please speak with a qualified professional."

---

## 17. Differentiation from a Typical AI Journaling Product

| Dimension | Typical AI Journaling App | 15 Signals |
|---|---|---|
| **Feedback basis** | Today's entry | Trend across multiple days |
| **Feedback type** | Summary, reflection, or questions back to the user | Interpretive analysis tied to a defined signal taxonomy |
| **Intellectual framing** | Generic wellness language | Specific thinkers and frameworks from philosophy, economics, theology, sociology |
| **What gets highlighted** | Everything the user mentioned | Only the 1–3 signals showing the strongest upward trend |
| **User model** | The user who wants to be heard or organized | The user who wants to understand what is happening in them over time |
| **Content depth** | Thin; generated freshly per entry without a durable model | Deep; built from a curated library with editorial intentionality |
| **Retention mechanic** | Habit-formation (streak, affirmation) | Accumulation value (the longer you write, the more accurate and meaningful the feedback) |
| **Tone** | Warm but generic | Warm and intellectually serious |
| **Therapeutic framing** | Often implicitly therapeutic | Explicitly not a therapeutic product; positioned as an observational tool |

The core differentiator is the **combination** of these three things, not any one alone: the fixed signal taxonomy (which creates precision), the trend-based detection (which creates temporal depth), and the thinker library (which creates intellectual substance). Any generic AI app can offer one of these; no competitor currently offers all three in a single coherent experience.

---

## 18. Possible Future Expansion Directions

These are not V1 commitments. They are directional possibilities to hold in mind as the product matures.

**1. Signal-Based Reading Lists**
The thinker library could expand into full curated reading recommendations — books, essays, and long-form articles — organized by the user's active signals. This turns 15 Signals into a personalized intellectual companion, not just a journaling tool.

**2. Conversational Depth Mode**
After reviewing their feedback, users could choose to enter a structured dialogue with the system — not a general chatbot, but a conversation constrained to exploring the active signal further, drawing on the thinker library. This preserves the product's intentional focus while adding interactivity.

**3. Cross-Signal Narrative**
As users accumulate months of data, the system could detect not just individual signal trends but recurring *combinations* of signals — patterns that appear together repeatedly. This would allow the product to offer higher-order observations about the user's psychological and existential structure, not just surface fluctuations.

**4. Thinker Subscription / Deep Dive Content**
Premium content layer in which users can access longer-form editorial material on specific thinkers — essays, annotated readings, or audio narration — organized around their personal signal history.

**5. Partner Integrations**
Integration with therapy or coaching platforms where users can share their 15 Signals trend report with a professional they are already working with. This is not the product becoming a therapy tool — it is the product serving as a preparation layer for people who are already in therapeutic relationships.

**6. Community (Carefully)**
A future anonymous, moderated community where users can share which signals are active for them (without sharing their entries) and read thinker perspectives alongside others experiencing the same signals. This would need careful design to avoid pathologizing or stigmatizing certain signal patterns.

**7. Multi-Language and Cultural Expansion**
The thinker library and signal taxonomy should eventually be extended to include non-Western traditions — Chinese philosophy, African philosophy, South Asian traditions — making the product genuinely global rather than implicitly Western.

---

## 19. Interaction Design Language

### Visual Style Reference

**One-line definition:** Literary Editorial — a high-end literary magazine built as a mobile app.

**Core references:** The product should feel like *The Paris Review* rendered as a mobile experience. Serious without coldness, deep without obscurity, visually restrained without cheapness.

#### Typography System

- **Display headlines:** Heavy display serif, high visual impact, strong print quality
- **Quotes / subtitles:** Italic serif, evoking manuscript or literary annotation
- **Body text:** Light serif or sans-serif, readability-first
- **Labels / navigation:** Small caps with wide tracking, understated and precise

#### Color

- Background: pure white or warm off-white — never cool gray
- Text: near-black — brand color does not fill content areas
- Accent: used only for borders or selection states, extremely restrained
- Overall: near-achromatic — color does not carry information; content does

#### Illustration Style

- Black-and-white woodcut / linocut aesthetic
- High contrast, dramatic, handcrafted quality
- No photography, no decorative iconography
- Each illustration stands alone as a work — more book cover than UI asset

#### Layout and Space

- Generous whitespace; content never crowds
- Card-based structure with minimal or invisible borders
- Clear content hierarchy: label → headline → body → action
- Option buttons: rounded rectangles, no fill color, distinguished by outline only

#### Tone of Interface Copy

- Labels: cool and precise ("Signal 01 / 15")
- Questions: open-ended, philosophical ("How much of your day felt like a performance?")
- Feedback text: narrative, literary in register — no bullet points

---

### Signature Interaction Pattern: The Oracle Transition

#### Core Metaphor

This is not a chat interface. It is not a form submission. It is not a loading state.

It is: **the user writes something down, the words dissolve from the page, and the response emerges from the same space.**

Input and output share a single spatial container. They are two tenses of the same surface — not two separate UI states.

#### Phase Breakdown

**Phase 1 — Inscription**
The user writes in a clean, borderless text area. No character counter, no submit button in sight. The cursor is the only focal point. Text appears in dark, solid ink — grounded and real.

**Phase 2 — Dissolution**
On submission, the user's text does not disappear — it **fades and diffuses outward**, like ink meeting water, bleeding toward transparency.
- Duration: 1.5–2 seconds
- Technique: opacity fade combined with subtle blur expansion
- No loading spinner. No progress indicator.
- **The silence of this moment is part of the experience.** Waiting is not a cost — it is the threshold.

**Phase 3 — Emergence**
The system's response text surfaces from the **center of the same container**.
- Not a typewriter effect (character by character)
- Instead: **the full text materializes from transparent to solid**, like a photograph developing in a darkroom
- Typography shifts to italic serif — a distinct voice, in the same space, answering
- Duration: 1–1.5 seconds

**Phase 4 — Resting**
Once fully visible, the text simply holds.
- No auto-scroll
- No immediate next-step prompt
- The user decides when to continue
- The feedback is allowed to exist in silence before the interface moves on

#### Psychological Effect

| Conventional AI Response | Oracle Transition |
|---|---|
| I sent a message | I wrote something down |
| The system is processing | Something is reading me |
| I received a reply | An answer surfaced from where I wrote |
| Feeling: a tool responded to me | Feeling: I shared a space with something that responded |

#### Implementation Constraints

This transition must be **slow and silent**. It must never feel like a "magic effect."

- No particles, no glows, no light trails, no sound
- Only opacity, blur, and time
- The animation curve should ease in slowly, ease out even more slowly — never snappy
- If the system response takes longer than expected to generate, the dissolution phase can extend slightly; the user should never see a spinner interrupt the transition

The authority of the Marauder's Map is not in its special effects. It is in the **certainty that something is there, reading back**.

#### Scope Note

This transition applies specifically to the **Journal Entry → Feedback** flow. It is the product's most distinctive interaction moment and should be treated as a signature, not a template to be reused across all transitions. Other navigational transitions in the app use standard, subdued motion — the Oracle Transition is reserved for the act of receiving a response to one's writing.

---

## Non-Goals

The following are explicitly outside the scope of this product, permanently or for the foreseeable future. These are not omissions — they are intentional boundaries.

1. **15 Signals is not a mental health treatment tool.** It will not offer therapy, counseling, or clinical intervention of any kind.
2. **It is not a crisis intervention service.** It is not designed to detect or respond to psychiatric emergencies. A basic safety layer will redirect users in acute distress to appropriate resources, but this is a floor, not a feature.
3. **It is not a personal productivity tool.** It does not help users manage tasks, set goals, track habits in a behavioral sense, or improve performance.
4. **It is not a social platform.** There is no following, sharing, commenting, or public profile in V1 or the foreseeable future.
5. **It is not a general-purpose AI chat experience.** The conversational layer, if it exists, is bounded by the signal taxonomy and thinker library. It is not a general assistant.
6. **It is not trying to compete with meditation apps.** The product does not offer guided relaxation, breathing exercises, or mindfulness practices.
7. **It is not a self-help program.** It does not prescribe behaviors, set objectives for the user, or measure progress against wellness benchmarks.
8. **It is not a research or data product.** Aggregate user signal data will not be sold, analyzed for third-party purposes, or used to build population-level psychological models without explicit, separate consent frameworks and ethical review.

---

*This document is a working draft for internal discussion. All assumptions, scope decisions, and design principles listed here are open for team review and revision before the PRD is finalized.*
