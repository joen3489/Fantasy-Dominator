# Reporter personas

The Front Office separates the evidence layer from the publication voice. Every
league profile stores a `writer_preferences.persona_id` and an optional
`writer_preferences.custom_instructions` note. The writer workflow resolves that
payload into one named persona before making each article call.

Available personas:

- `front_office` — dry, confident, lightly smug, and explicit about the next decision.
- `scout` — role- and usage-first, measured, and focused on what must be true next.
- `commissioner` — playful league politics with a warm, mischievous sense of the room.
- `quant` — terse, comparison-driven, and numbers-first with minimal theater.

The custom note is capped at 800 characters. It can focus the editor on a league
convention or preference, but it cannot override source evidence, citations,
read-only behavior, or the shared forbidden-language checks. A generated article
records the persona in front matter and in the per-league `content_artifacts`
receipt. The browser issue exposes the same persona so the reader knows who is
writing the edition.
