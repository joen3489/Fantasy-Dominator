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
- `dossier_dana` - multi-season roster construction and manager behavior.

Default article assignments:

| Article | Reporter |
| --- | --- |
| `team_report` | Topline Tony |
| `market_watch` | Waiver Wire Waverly |
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
