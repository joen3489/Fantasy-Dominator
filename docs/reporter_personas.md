# Reporter personas

The Front Office separates the evidence layer from the publication voice. Every
league profile stores a backwards-compatible `writer_preferences.persona_id` and
an optional `writer_preferences.custom_instructions` note. The writer workflow
also resolves an article-specific newsroom lineup from
`writer_preferences.article_reporters`. The lineup defaults are distinct even
when no league customization exists.

Available personas:

- `front_office` - dry, confident, lightly smug, and explicit about the next decision.
- `scout` - role- and usage-first, measured, and focused on what must be true next.
- `commissioner` - playful league politics with a warm, mischievous sense of the room.
- `quant` - terse, comparison-driven, and numbers-first with minimal theater.
- `topline_tony` - weekly stakes, matchups, moves, and the league's top-line story.
- `waiver_wire_waverly` - risers, fallers, waiver fits, and role-change evidence.
- `trade_desk_talia` - counterparty incentives, value disagreements, and trade fits.
- `look_ahead_lonnie` - playoff windows, schedules, deadlines, and future stashes.
- `market_clock_morgan` - separates next-game, rest-of-season, dynasty, and career-window value.
- `dossier_dana` - multi-season roster construction and manager behavior.

Default article assignments:

| Article | Reporter |
| --- | --- |
| `team_report` | Topline Tony |
| `market_watch` | Waiver Wire Waverly |
| `horizon_watch` | Market Clock Morgan |
| `trade_desk` | Trade Desk Talia |
| `manager_intel` | Dossier Dana |
| `daily_brief` | Look-Ahead Lonnie |

An individual league can override an assignment without flattening the edition:

```json
{
  "persona_id": "front_office",
  "article_reporters": {
    "trade_desk": "quant",
    "daily_brief": "topline_tony"
  }
}
```

The custom note is capped at 800 characters. It can focus the editor on a league
convention or preference, but it cannot override source evidence, citations,
read-only behavior, or the shared forbidden-language checks. A generated article
records the resolved reporter in front matter and in the per-league
`content_artifacts` receipt. The browser issue exposes the lineup so the reader
knows which lens is writing each section.

## 2026-08-26 market-clock editorial boundary

The four-window scores are deterministic facts; the newsroom assigns the
interpretation by decision window. Market Clock Morgan owns the league-wide
comparison of this week, rest of season, dynasty, and career-window scores.
Waiver Wire Waverly owns the available-market research lane and may use the
same windows to explain whether an available name is a contender add or a
rebuilder stash. This is an additive editorial split over one evidence model,
not a second set of scores and not a reason to regenerate the same article four
times. Every voice must preserve missing-window coverage, availability status,
market value as the cross-position price anchor, the four clock-versus-market
deltas, and the waiver-eligibility limitation.

## 2026-08-26 naming clarification

The live model now has four decision windows: next game, rest of season,
dynasty market, and a separate five-year career-window scenario. The UI and
writer contract call the combined section “Four-Window Market Read” so the
career scenario is visible without being mistaken for a dollar market or hidden
inside dynasty value. Older “three-clock” references remain only as dated
historical notes.

## 2026-08-26 horizon newsroom design

The four scores are a shared market instrument, not four disconnected
rankings. New articles or reporters may sit on top of the instrument when they
answer a different manager question:

| Editorial question | Primary evidence | Best-fit desk |
| --- | --- | --- |
| Who helps me win the next game? | `next_game_market_score`, availability, opponent, and matchup receipt | Topline Tony |
| Who compounds through the current season? | `rest_of_season_market_score`, scheduled games, byes, and baseline PPG | Waiver Wire Waverly |
| Who belongs in a dynasty window? | `dynasty_market_score`, age, market percentile, and timeline deltas | Look-Ahead Lonnie |
| What is the bounded career scenario worth? | `career_projection_score`, history join, and age-curve basis | Look-Ahead Lonnie |
| Where do contender and rebuilder values diverge? | `contender_fit_score`, `rebuilder_fit_score`, transition deltas, and clock-versus-market leads | Market Clock Morgan and Trade Desk Talia |

The default lineup also carries an explicit decision-lens receipt: Topline Tony
is `next_game`, Waiver Wire Waverly is `rest_of_season`, Look-Ahead Lonnie is
`dynasty_career`, and Market Clock Morgan is `multi_window`. The lens controls
what the writer prioritizes, not which facts are available; every desk still
receives the validated packet and must disclose missing or unavailable clocks.

The same evidence packet may power several sections, but a new paid article is
justified only when its decision, audience, or evidence selection is distinct.
Writers can disagree about emphasis and actionability; they cannot recalculate
scores, collapse position-relative percentiles into a universal ranking, or
describe a repricing lead as proven mispricing. Unchanged evidence fingerprints
should reuse existing content rather than create four near-identical articles.

## Desk editor

The newsroom has one final editor, **The Desk Editor**, between writer output
and publication. A deterministic gate always checks that every story has a
headline, thesis, what-changed section, action section, evidence IDs, source
IDs, and a supported generation mode. When `FRONT_OFFICE_EDITOR_MODE=llm` is
explicitly enabled for a paid run, Luna receives the same canonical evidence
packet plus the draft and may `approve`, `modify`, or `hold`. A modification
must be a complete replacement that passes the same validator; a held story is
retained for inspection but its body and action copy are not printed. The
editor may repair framing and caveats, but cannot add facts, scores, motives,
transactions, or source claims. The deterministic gate remains code-owned and
authoritative.

Writers may receive bounded previous-edition and peer-edition excerpts to
create continuity and disagreement. Those excerpts are room context, not
evidence. The assigned desk must still follow its declared horizon: Topline
Tony answers the next-game question, Waiver Wire Waverly answers the current
season, and Look-Ahead Lonnie answers the dynasty/career question. Historical
data may support any of them, but it cannot silently substitute for the most
relevant current window.
