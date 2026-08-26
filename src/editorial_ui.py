from __future__ import annotations

"""Presentation-only layer for the generated Front Office reader surface.

Keeping this separate from the data-room template lets the issue evolve like a
publication without making the canonical tables harder to inspect or test.
"""


EDITORIAL_STYLE = r"""
    .issue-shell {
      margin: 0 0 34px;
      border: 1px solid #c8d2c5;
      border-radius: 14px;
      overflow: hidden;
      background: #fbfcf8;
      box-shadow: 0 10px 30px rgba(32, 39, 34, .08);
    }
    .issue-hero {
      position: relative;
      isolation: isolate;
      padding: clamp(22px, 4vw, 42px);
      color: #f8f4ea;
      background:
        radial-gradient(circle at 88% 20%, rgba(196, 155, 68, .22), transparent 32%),
        linear-gradient(135deg, #202722 0%, #173f35 100%);
    }
    .editorial-masthead-picture {
      position: absolute;
      z-index: -1;
      inset: 0;
      display: block;
      overflow: hidden;
      background: #173f35;
    }
    .editorial-masthead-picture img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center;
      opacity: .92;
    }
    .issue-hero::after {
      position: absolute;
      z-index: -1;
      inset: 0;
      content: "";
      pointer-events: none;
      background: linear-gradient(90deg, rgba(32,39,34,.96) 0%, rgba(23,63,53,.78) 48%, rgba(23,63,53,.28) 100%);
    }
    .issue-hero > *:not(.editorial-masthead-picture) { position: relative; z-index: 1; }
    .issue-hero.has-masthead {
      background-position: center;
      background-size: cover;
      background-blend-mode: multiply;
    }
    .issue-kicker-row, .issue-byline, .story-kicker-row, .story-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .issue-kicker {
      color: #d4c38e;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    .issue-date, .issue-byline {
      color: #b7c4b9;
      font-size: 12px;
    }
    .issue-date { margin-left: auto; }
    .issue-title-row {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
      margin-top: 18px;
    }
    .issue-title {
      max-width: 860px;
      margin: 0;
      color: #fffaf0;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(30px, 5vw, 56px);
      font-weight: 700;
      letter-spacing: -.025em;
      line-height: .98;
    }
    .issue-dek {
      max-width: 760px;
      margin: 16px 0 0;
      color: #d7e2d8;
      font-size: clamp(15px, 2vw, 19px);
      line-height: 1.45;
    }
    .issue-writer-mode { flex: 0 0 auto; background: #d4c38e; color: #202722; }
    .issue-reporter { color: #d7e2d8; font-size: 12px; font-weight: 800; }
    .issue-byline { margin-top: 22px; }
    .issue-byline span { display: inline-flex; align-items: center; gap: 6px; }
    .issue-byline span + span::before { content: "•"; color: #789181; }
    .issue-quick-links { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
    .issue-quick-links a { display: inline-block; padding: 7px 10px; border: 1px solid rgba(215, 226, 216, .35); border-radius: 999px; color: #f2dfaa; font-size: 12px; font-weight: 800; text-decoration: none; }
    .issue-quick-links a:hover { background: rgba(215, 226, 216, .12); }
    .editorial-layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(220px, 285px);
      gap: 14px;
      padding: 18px;
      background: #eef2eb;
    }
    .front-page-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 0 18px 18px;
      background: #eef2eb;
    }
    .front-page-panel {
      min-width: 0;
      padding: 15px;
      border: 1px solid var(--line);
      border-top: 4px solid var(--info);
      border-radius: 10px;
      background: var(--panel);
    }
    .front-page-panel.tone-market { border-top-color: var(--buy); }
    .front-page-panel.tone-news { border-top-color: var(--alert); }
    .front-page-panel.tone-manager { border-top-color: var(--watch); }
    .front-page-panel.tone-team { border-top-color: var(--gold); }
    .front-page-panel h3 { margin: 5px 0 7px; font-family: Georgia, "Times New Roman", serif; font-size: 21px; line-height: 1.05; }
    .front-page-panel .panel-eyebrow { color: var(--accent); font-size: 10px; font-weight: 900; letter-spacing: .08em; text-transform: uppercase; }
    .front-page-panel .panel-dek { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.4; }
    .front-page-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; margin: 12px 0; }
    .front-page-fact { padding: 7px 8px; border-radius: 7px; background: #f1f3ed; }
    .front-page-fact strong { display: block; font-size: 15px; line-height: 1.05; }
    .front-page-fact span { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; line-height: 1.2; }
    .front-page-items { display: grid; gap: 8px; }
    .front-page-item { padding-top: 8px; border-top: 1px dashed var(--line); }
    .front-page-item:first-child { padding-top: 0; border-top: 0; }
    .front-page-item h4 { margin: 0 0 3px; font-size: 13px; line-height: 1.2; }
    .front-page-item h4 a { color: var(--ink); text-decoration: none; }
    .front-page-item h4 a:hover { color: var(--accent); text-decoration: underline; }
    .front-page-item p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.38; }
    .front-page-item .item-meta { margin-top: 4px; color: var(--accent); font-size: 10px; font-weight: 800; line-height: 1.25; }
    .front-page-panel .panel-uncertainty { margin: 12px 0 0; padding-top: 9px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; line-height: 1.35; }
    .front-page-panel .panel-route { display: inline-block; margin-top: 11px; color: var(--accent); font-size: 11px; font-weight: 900; text-decoration: none; }
    .front-page-panel .panel-route:hover { text-decoration: underline; }
    .editorial-story {
      min-width: 0;
      border: 1px solid var(--line);
      border-left: 5px solid var(--info);
      border-radius: 10px;
      padding: 18px;
      background: var(--panel);
    }
    .editorial-story.tone-market { border-left-color: var(--buy); }
    .editorial-story.tone-sell { border-left-color: var(--sell); }
    .editorial-story.tone-hold { border-left-color: var(--hold); }
    .editorial-story.tone-news { border-left-color: var(--alert); }
    .editorial-story.tone-manager { border-left-color: var(--watch); }
    .editorial-lead {
      min-height: 300px;
      border: 0;
      border-left: 5px solid var(--gold);
      color: #f8f4ea;
      background: #202722;
      box-shadow: 0 8px 20px rgba(32, 39, 34, .12);
    }
    .editorial-lead .story-kicker { color: #d4c38e; }
    .editorial-lead .story-title, .editorial-lead .story-title a { color: #fffaf0; }
    .editorial-lead .story-dek { color: #d7e2d8; }
    .editorial-lead .story-action { color: #f2dfaa; }
    .editorial-lead .story-chip { color: #e4efe9; border-color: rgba(228, 239, 233, .22); background: rgba(228, 239, 233, .08); }
    .editorial-lead .evidence-drawer { border-color: rgba(228, 239, 233, .22); }
    .editorial-lead .evidence-drawer summary { color: #d4c38e; }
    .editorial-lead .brief-card-evidence { color: #c5d0c6; }
    .story-kicker {
      color: var(--accent);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .story-score { margin-left: auto; }
    .story-title {
      margin: 16px 0 8px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(22px, 3vw, 34px);
      line-height: 1.05;
      letter-spacing: -.015em;
    }
    .editorial-card .story-title { font-size: 22px; }
    .story-title a { color: var(--ink); text-decoration: none; }
    .story-title a:hover { text-decoration: underline; }
    .story-dek { margin: 0; color: var(--muted); font-size: 15px; line-height: 1.5; }
    .story-action { margin: 16px 0 0; color: var(--accent); font-size: 14px; line-height: 1.45; }
    .story-meta { margin-top: 16px; }
    .story-chip {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      color: #34403b;
      background: #fbfcf8;
      font-size: 11px;
      font-weight: 800;
    }
    .story-chip.confidence-high { color: var(--buy); background: var(--buy-bg); }
    .story-chip.confidence-medium { color: #7a5f28; background: var(--watch-bg); }
    .story-chip.confidence-low { color: var(--sell); background: var(--sell-bg); }
    .story-details { margin-top: 18px; }
    .story-details .claim-grid { margin-top: 10px; }
    .claim-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 7px;
    }
    .claim-item { padding: 8px 9px; border-radius: 7px; background: rgba(15, 92, 74, .07); }
    .claim-label { display: block; color: var(--muted); font-size: 10px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; }
    .claim-value { display: block; margin-top: 3px; color: var(--ink); font-size: 13px; line-height: 1.25; }
    .editorial-lead .claim-item { background: rgba(228, 239, 233, .08); }
    .editorial-lead .claim-label { color: #9fb3a4; }
    .editorial-lead .claim-value { color: #f8f4ea; }
    .source-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .source-link { color: var(--accent); font-size: 12px; font-weight: 800; }
    .editorial-lead .source-link { color: #d4c38e; }
    .issue-pulse {
      align-self: stretch;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
    }
    .issue-pulse h3 { margin-bottom: 14px; font-family: Georgia, "Times New Roman", serif; font-size: 22px; }
    .pulse-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .pulse-metric { padding: 10px; border-radius: 7px; background: #f1f3ed; }
    .pulse-metric strong { display: block; font-size: 22px; line-height: 1; }
    .pulse-metric span { display: block; margin-top: 5px; color: var(--muted); font-size: 11px; line-height: 1.25; }
    .health-heading { margin: 22px 0 8px; color: var(--muted); font-size: 11px; font-weight: 900; letter-spacing: .08em; text-transform: uppercase; }
    .health-list { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
    .health-row { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; }
    .health-row span:last-child { font-weight: 800; }
    .health-current { color: var(--buy); }
    .health-limited { color: var(--sell); }
    .editorial-divider { display: flex; align-items: center; gap: 12px; margin: 22px 18px 12px; color: var(--muted); font-size: 11px; font-weight: 900; letter-spacing: .1em; text-transform: uppercase; }
    .editorial-divider::after { content: ""; height: 1px; flex: 1; background: var(--line); }
    .editorial-story-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; padding: 0 18px 18px; }
    .editorial-story-grid .editorial-story { padding: 15px; }
    .editorial-story-grid .story-action { margin-top: 12px; }
    .publication-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; padding: 0 18px 20px; }
    .publication-card { background: #fffdf7; border: 1px solid var(--line); border-radius: 16px; padding: 18px; box-shadow: 0 8px 22px rgba(19, 35, 27, .05); }
    .publication-card.publication-layout-feature { grid-column: 1 / -1; border-top: 4px solid var(--gold); }
    .publication-card.publication-layout-wide { grid-column: span 2; }
    .publication-card.publication-layout-rail { grid-column: span 1; }
    .publication-card h3 { margin: 0 0 6px; font-family: Georgia, serif; font-size: 24px; }
    .publication-card .publication-meta { display: flex; flex-wrap: wrap; gap: 7px; margin: 0 0 12px; color: var(--muted); font-size: 12px; }
    .publication-media { margin: 0 0 14px; overflow: hidden; border-radius: 10px; background: #e8ece5; }
    .publication-media img { display: block; width: 100%; aspect-ratio: 3 / 2; object-fit: cover; }
    .publication-media figcaption { padding: 6px 9px; color: var(--muted); background: #f1f3ed; font-size: 10px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
    .publication-card .publication-receipt { margin-top: 14px; color: var(--muted); font-size: 12px; }
    .publication-review-approved { color: var(--buy); border-color: rgba(31, 111, 82, .35); }
    .publication-review-held-label { color: var(--sell); border-color: rgba(154, 63, 45, .35); }
    .publication-review-held { margin: 12px 0; padding: 13px; border: 1px solid rgba(154, 63, 45, .28); border-radius: 10px; background: #fff2ed; color: var(--sell); }
    .publication-review-held p { margin: 6px 0 0; color: var(--muted); line-height: 1.45; }
    .publication-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
    .publication-actions button { border: 1px solid var(--line); border-radius: 999px; background: #f7f8f3; color: var(--accent); padding: 7px 10px; font-size: 11px; font-weight: 800; cursor: pointer; }
    .publication-actions button:hover { background: #e4efe9; }
    .publication-actions button:disabled { opacity: .65; cursor: default; }
    .publication-outcome { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--line); }
    .publication-outcome label { display: grid; gap: 4px; color: var(--muted); font-size: 11px; font-weight: 800; }
    .publication-outcome select { border: 1px solid var(--line); border-radius: 7px; background: #fbfcf8; color: var(--ink); padding: 7px 9px; font-size: 12px; }
    .publication-outcome button { border: 1px solid var(--accent); border-radius: 999px; background: var(--buy-bg); color: var(--accent); padding: 7px 10px; font-size: 11px; font-weight: 800; cursor: pointer; }
    .publication-outcome button:disabled { opacity: .65; cursor: default; }
    .publication-card .article-body { color: var(--ink); }
    .publication-card .article-p { line-height: 1.6; }
    .publication-card .publication-list-block { margin: 14px 0; }
    .publication-card .publication-list-block > .article-list { margin: 0; }
    .publication-list-item { padding: 9px 0 9px 2px; border-bottom: 1px solid rgba(200, 210, 197, .72); }
    .publication-list-item:last-child { border-bottom: 0; }
    .publication-list-item > p { margin: 0; line-height: 1.48; }
    .publication-list-item > p strong { color: var(--accent); }
    .publication-list-item .evidence-drawer { margin-top: 7px; }
    .publication-list-item .evidence-drawer summary { font-size: 11px; }
    .publication-more { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--line); }
    .publication-more summary { color: var(--accent); font-size: 12px; font-weight: 900; cursor: pointer; }
    .publication-more .article-list { margin-top: 8px; }
    .publication-summary { margin: 0 0 14px; padding: 12px 13px; border-left: 3px solid var(--gold); background: #f4f0df; border-radius: 8px; }
    .publication-summary p { margin: 5px 0 0; color: var(--muted); line-height: 1.45; }
    .publication-summary strong { color: var(--ink); }
    .learning-ledger { margin: 0 18px 18px; }
    .learning-ledger .tile-row { padding: 0; }
    .edition-changes, .media-ledger { margin: 0 18px 18px; }
    .edition-change-list { display: grid; gap: 8px; }
    .edition-change { padding: 10px 12px; border: 1px solid var(--line); border-radius: 9px; background: #fbfcf8; }
    .edition-change strong { margin-left: 8px; }
    .edition-change .note { margin: 6px 0 0; }
    .question-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 0 18px 18px; }
    .question-card { display: block; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); padding: 13px; }
    .question-card strong { display: block; margin-bottom: 5px; font-size: 13px; }
    .question-card span { display: block; color: var(--muted); font-size: 12px; line-height: 1.4; }
    @media (max-width: 720px) { .publication-grid { grid-template-columns: 1fr; padding-left: 12px; padding-right: 12px; } }
    .issue-data-drawer { margin: 0 18px 12px; }
    .issue-data-drawer:last-child { margin-bottom: 18px; }
    .issue-data-drawer summary { display: flex; justify-content: space-between; gap: 10px; align-items: center; padding: 3px 0; color: var(--ink); font-size: 14px; }
    .summary-note { color: var(--muted); font-size: 12px; font-weight: 500; }
    .issue-data-drawer[open] summary { margin-bottom: 12px; }
    .issue-data-drawer .article-panel { border: 0; padding: 0; }
    .data-room-intro { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 14px; align-items: center; margin-bottom: 14px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 8px; background: #eef2eb; }
    .data-room-intro p { margin: 0; }
    .question-led-intro { margin-bottom: 10px; }
    .question-led-intro h2 { margin: 4px 0 6px; font-family: Georgia, "Times New Roman", serif; font-size: 25px; }
    .section-kicker { color: var(--accent); font-size: 11px; font-weight: 900; letter-spacing: .08em; text-transform: uppercase; }
    .data-room-question-grid { display: flex; flex-wrap: wrap; gap: 7px; margin: 0 0 12px; }
    .data-room-question { border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--ink); padding: 8px 11px; font-size: 12px; font-weight: 800; cursor: pointer; }
    .data-room-question:hover, .data-room-question.active { border-color: var(--accent); background: var(--buy-bg); color: var(--accent); }
    .question-answer { margin: 0 0 12px; padding: 14px 16px; border: 1px solid var(--line); border-left: 4px solid var(--gold); border-radius: 8px; background: #fffdf7; line-height: 1.5; }
    .question-answer strong { color: var(--ink); }
    .decision-visual-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 18px; }
    .decision-visual { padding: 13px; border: 1px solid var(--line); border-radius: 9px; background: var(--panel); }
    .decision-visual h3 { margin: 0 0 9px; font-family: Georgia, "Times New Roman", serif; font-size: 18px; }
    .decision-bar-row { display: grid; grid-template-columns: minmax(80px, 1fr) minmax(80px, 2fr) auto; gap: 8px; align-items: center; margin: 8px 0; font-size: 12px; }
    .decision-bar-track { height: 8px; overflow: hidden; border-radius: 999px; background: #e8ece5; }
    .decision-bar-fill { height: 100%; border-radius: inherit; background: var(--accent); }
    .decision-bar-value { color: var(--muted); font-weight: 800; }
    .decision-list { margin: 0; padding-left: 17px; color: var(--muted); font-size: 13px; line-height: 1.5; }
    @media (max-width: 900px) {
      .editorial-layout { grid-template-columns: 1fr; }
      .front-page-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .editorial-story-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 620px) {
      .issue-title-row { display: grid; align-items: start; }
      .issue-date { margin-left: 0; }
      .front-page-grid { grid-template-columns: 1fr; padding-left: 12px; padding-right: 12px; }
      .editorial-story-grid { grid-template-columns: 1fr; }
      .question-grid { grid-template-columns: 1fr; padding-left: 12px; padding-right: 12px; }
      .issue-data-drawer { margin-left: 12px; margin-right: 12px; }
      .editorial-story-grid { padding-left: 12px; padding-right: 12px; }
      .editorial-divider { margin-left: 12px; margin-right: 12px; }
      .data-room-intro { grid-template-columns: 1fr; }
      .decision-visual-grid { grid-template-columns: 1fr; }
    }
"""


EDITORIAL_HTML = """    <div id="todays-board" class="view-block">
      <div class="issue-shell" data-testid="editorial-issue">
        <div class="issue-hero" data-media-slot="masthead">
          <picture id="issue-masthead-picture" class="editorial-masthead-picture" data-editorial-masthead aria-hidden="true"></picture>
          <div class="issue-kicker-row">
            <span id="issue-kicker" class="issue-kicker">Personal league edition</span>
            <span id="issue-date" class="issue-date">Latest refresh</span>
          </div>
          <div class="issue-title-row">
            <div>
              <h2 id="issue-headline" class="issue-title">Your edition is loading</h2>
              <p id="issue-dek" class="issue-dek">The analyst is assembling the current read from your league data.</p>
            </div>
            <span id="issue-writer-mode" class="tag issue-writer-mode">Evidence-led template</span>
          </div>
          <div class="issue-byline">
            <span id="issue-reporter">Reporter is loading</span>
            <span id="issue-as-of">As of the latest refresh</span>
            <span id="issue-freshness">Freshness is loading</span>
            <span id="issue-latest-news">Latest news is loading</span>
            <span id="issue-publication-receipt">Publication receipt is loading</span>
          </div>
          <div class="issue-quick-links"><a href="#view-draft-room">Open the Draft Room</a><a href="#view-my-team">Open My Team</a></div>
          <div id="issue-publication-nav" class="issue-quick-links" aria-label="Open desk reports"></div>
        </div>
        <div class="editorial-layout">
          <div id="issue-lead"></div>
          <aside class="issue-pulse">
            <h3>Signal pulse</h3>
            <div id="issue-pulse-metrics" class="pulse-metrics"></div>
            <div class="health-heading">Source health</div>
            <ul id="issue-source-health" class="health-list"></ul>
          </aside>
        </div>
        <div class="editorial-divider"><span>Front page desk</span></div>
        <div id="issue-front-page" class="front-page-grid" data-testid="front-page-desk"></div>
        <div class="editorial-divider"><span>More from this edition</span></div>
        <div id="issue-stories" class="editorial-story-grid"></div>
        <div class="editorial-divider"><span>Desk reports</span></div>
        <div id="issue-publication" class="publication-grid"></div>
        <div class="editorial-divider"><span>Read by question</span></div>
        <div id="issue-questions" class="question-grid"></div>
        <details class="data-drawer issue-data-drawer">
          <summary><span>Today's Board</span><span class="summary-note">ranked signals</span></summary>
          <div id="today-priority-board"></div>
        </details>
        <details class="data-drawer issue-data-drawer">
          <summary><span>Read the full analyst brief</span><span id="daily-gm-brief-mode" class="tag"></span></summary>
          <div id="daily-gm-brief"></div>
        </details>
      </div>
    </div>
"""


EDITORIAL_JS = r"""
    function renderEditorial() {
      const issue = editorial || {};
      renderEditorialMedia();
      setText('issue-kicker', issue.kicker || 'Personal league edition');
      setText('issue-date', issue.edition_label || 'Latest refresh');
      setText('issue-headline', issue.headline || 'Your edition is waiting for a refresh');
      setText('issue-dek', issue.dek || 'No editorial read has been compiled yet.');
      setText('issue-as-of', issue.as_of_label || 'As of the latest refresh');
      setText('issue-reporter', (issue.reporter_persona || {}).name || 'The Front Office');
      setText('issue-freshness', issue.freshness_label || 'Freshness unavailable');
      setText('issue-writer-mode', issue.writer_mode || 'Evidence-led template');
      setText('issue-latest-news', issue.latest_news_label ? `Latest news ${issue.latest_news_label}` : 'Latest news not recorded');
      const manifestReceipts = manifest.articleReceipts || {};
      const receiptCount = Object.keys(manifestReceipts).length;
      setText('issue-publication-receipt', `${receiptCount} article receipts · bundle ${String(manifest.bundleRevision || 'unbound').slice(0, 12)}`);
      const freshness = issue.source_health_summary || {};
      const freshnessNode = document.getElementById('issue-freshness');
      if (freshnessNode) freshnessNode.className = freshness.healthy === freshness.total ? 'health-current' : 'health-limited';
      document.getElementById('issue-lead').innerHTML = editorialStoryMarkup(issue.lead || {}, true);
      const frontPage = document.getElementById('issue-front-page');
      if (frontPage) {
        const panels = issue.front_page_panels || [];
        frontPage.innerHTML = panels.length
          ? panels.map(frontPagePanelMarkup).join('')
          : '<p class="note">The front-page desk has no connected panels yet. Open the Data Room to inspect the available evidence.</p>';
      }
      document.getElementById('issue-stories').innerHTML = (issue.stories || []).length
        ? (issue.stories || []).map(story => editorialStoryMarkup(story, false)).join('')
        : '<p class="note">The edition has no secondary stories yet. That may be a quiet board, or a data problem worth opening below.</p>';
      const publications = issue.publication_articles || [];
      document.getElementById('issue-publication').innerHTML = publications.length
        ? publications.map(publicationArticleMarkup).join('')
        : '<p class="note">No generated desk reports are published for this edition yet. The evidence-led board remains available below.</p>';
      const publicationNav = document.getElementById('issue-publication-nav');
      if (publicationNav) publicationNav.innerHTML = publications.length
        ? publications.map(article => `<a href="#publication-${escapeHtml(article.key || '')}">${escapeHtml(article.title || article.key || 'Desk report')}</a>`).join('')
        : '<span class="note">Desk reports appear here when their evidence packet is available.</span>';
      const questions = issue.question_prompts || [];
      document.getElementById('issue-questions').innerHTML = questions.length
        ? questions.map(prompt => `<a class="question-card" href="${escapeHtml(prompt.route || '#view-data-room')}"><strong>${escapeHtml(prompt.question || 'Open the data room')}</strong><span>${escapeHtml(prompt.answer || '')}</span></a>`).join('')
        : '<p class="note">Open the data room to choose a question.</p>';
      document.getElementById('issue-pulse-metrics').innerHTML = editorialPulse(issue.signal_summary || {});
      document.getElementById('issue-source-health').innerHTML = editorialHealth(issue.source_health || []);
      hydrateContentInteractions();
    }

    function frontPagePanelMarkup(panel) {
      const tone = String(panel.tone || 'info').replace(/[^a-z0-9_-]/gi, '');
      const route = String(panel.route || '#view-data-room').startsWith('#') ? String(panel.route || '#view-data-room') : '#view-data-room';
      const facts = (panel.facts || []).map(fact => `<div class="front-page-fact"><strong>${escapeHtml(String(fact.value ?? ''))}</strong><span>${escapeHtml(fact.label || 'Fact')}</span></div>`).join('');
      const items = (panel.items || []).map(item => {
        const anchor = String(item.anchor || '').replace(/[^a-zA-Z0-9:_-]/g, '');
        const title = anchor ? `<a href="#${escapeHtml(anchor)}">${escapeHtml(item.title || 'Untitled read')}</a>` : escapeHtml(item.title || 'Untitled read');
        return `<article class="front-page-item"><h4>${title}</h4><p>${escapeHtml(item.summary || '')}</p><p class="item-meta">${escapeHtml(item.meta || '')}</p><details class="evidence-drawer"><summary>Evidence</summary><p class="brief-card-evidence">${escapeHtml(item.evidence || 'Evidence trace not recorded.')}</p></details></article>`;
      }).join('');
      return `<article class="front-page-panel tone-${tone}" data-panel-key="${escapeHtml(panel.key || '')}"><div class="panel-eyebrow">${escapeHtml(panel.eyebrow || 'Desk')}</div><h3>${escapeHtml(panel.title || 'Front page desk')}</h3><p class="panel-dek">${escapeHtml(panel.dek || '')}</p>${facts ? `<div class="front-page-facts">${facts}</div>` : ''}<div class="front-page-items">${items || '<p class="note">No connected items are available for this desk.</p>'}</div>${panel.uncertainty ? `<p class="panel-uncertainty"><strong>Limit:</strong> ${escapeHtml(panel.uncertainty)}</p>` : ''}<a class="panel-route" href="${escapeHtml(route)}">${escapeHtml(panel.route_label || 'Open the evidence')} →</a></article>`;
    }

    function renderEditorialMedia() {
      const hero = document.querySelector('[data-media-slot="masthead"]');
      const assets = (app && app.mediaManifest && app.mediaManifest.assets) || [];
      const asset = assets.find(item => String(item.asset_type || '') === 'masthead');
      const sectionAssets = assets.filter(item => String(item.asset_type || '') === 'section_art');
      const receipt = document.getElementById('media-ledger-body');
      const safePath = value => {
        const path = String(value || '').trim();
        return path && !path.includes('://') && !path.startsWith('//') && !path.includes('..') ? path : '';
      };
      const usable = value => ['available', 'published'].includes(String(value || '').toLowerCase());
      if (!hero || !asset) {
        if (receipt) receipt.innerHTML = '<p class="note">No editorial media asset is configured. Typography and evidence remain available.</p>';
        return;
      }
      const path = safePath(asset.path);
      const variants = Array.isArray(asset.variants) ? asset.variants.filter(item => usable(item.status) && safePath(item.path)) : [];
      const picture = document.getElementById('issue-masthead-picture');
      if (!picture || !usable(asset.status) || !path) {
        if (receipt) receipt.innerHTML = `<p class="note">Masthead status: ${escapeHtml(asset.status || 'unavailable')}. Text publication is unaffected.</p>`;
        return;
      }
      const sources = variants.map(item => `<source media="${escapeHtml(item.media || '')}" srcset="${escapeHtml(safePath(item.path))}" sizes="${escapeHtml(item.sizes || asset.sizes || '100vw')}">`).join('');
      picture.innerHTML = `${sources}<img src="${escapeHtml(path)}" alt="${escapeHtml(asset.alt_text || '')}" loading="${escapeHtml(asset.loading || 'eager')}" fetchpriority="${escapeHtml(asset.fetchpriority || 'high')}" decoding="async"${asset.width ? ` width="${escapeHtml(String(asset.width))}"` : ''}${asset.height ? ` height="${escapeHtml(String(asset.height))}"` : ''}>`;
      const image = picture.querySelector('img');
      image.addEventListener('error', () => {
        picture.hidden = true;
        hero.classList.remove('has-masthead');
        hero.dataset.mediaStatus = 'unavailable';
        if (receipt) receipt.innerHTML = '<p class="note">The masthead failed to load. The evidence-led publication is still available without it.</p>';
      }, { once: true });
      hero.classList.add('has-masthead');
      hero.dataset.mediaStatus = asset.status || 'available';
      if (receipt) {
        const sectionReceipt = sectionAssets.length
          ? `<p class="note"><strong>Desk art:</strong> ${sectionAssets.map(item => `${escapeHtml(item.article_key || 'section')} · ${escapeHtml(item.status || 'unavailable')} · ${escapeHtml(item.reporter_id || 'unassigned')}`).join(' · ')}</p>`
          : '<p class="note">No article-specific desk art is configured.</p>';
        receipt.innerHTML = `<p class="note"><strong>${escapeHtml(asset.asset_id || 'Masthead')}</strong> · ${escapeHtml(asset.status || 'available')} · ${variants.length} responsive variant${variants.length === 1 ? '' : 's'}. Decorative only; no factual claims are carried by this artwork.</p><p class="note">Alt text: ${escapeHtml(asset.alt_text || 'Not supplied')} · Prompt hash: ${escapeHtml(String(asset.prompt_hash || 'not recorded').slice(0, 16))}…</p>${sectionReceipt}`;
      }
    }

    function publicationMediaPath(value) {
      const path = String(value || '').trim();
      return path && !path.includes('://') && !path.startsWith('//') && !path.includes('..') ? path : '';
    }

    function publicationMediaAsset(articleKey) {
      const assets = (app && app.mediaManifest && app.mediaManifest.assets) || [];
      return assets.find(item => String(item.asset_type || '') === 'section_art'
        && String(item.article_key || '') === String(articleKey || '')
        && ['available', 'published'].includes(String(item.status || '').toLowerCase())
        && publicationMediaPath(item.path)) || null;
    }

    function publicationMediaMarkup(articleKey) {
      const asset = publicationMediaAsset(articleKey);
      if (!asset) return '';
      const variants = Array.isArray(asset.variants)
        ? asset.variants.filter(item => ['available', 'published'].includes(String(item.status || '').toLowerCase()) && publicationMediaPath(item.path))
        : [];
      const sources = variants.map(item => `<source media="${escapeHtml(item.media || '')}" srcset="${escapeHtml(publicationMediaPath(item.path))}" sizes="${escapeHtml(item.sizes || asset.sizes || '100vw')}">`).join('');
      return `<figure class="publication-media" data-media-asset="${escapeHtml(asset.asset_id || articleKey || 'section-art')}">${sources}<img src="${escapeHtml(publicationMediaPath(asset.path))}" alt="${escapeHtml(asset.alt_text || 'Decorative editorial artwork')}" loading="${escapeHtml(asset.loading || 'lazy')}" fetchpriority="${escapeHtml(asset.fetchpriority || 'auto')}" decoding="async"${asset.width ? ` width="${escapeHtml(String(asset.width))}"` : ''}${asset.height ? ` height="${escapeHtml(String(asset.height))}"` : ''}><figcaption>Desk atmosphere · decorative only</figcaption></figure>`;
    }

    function publicationArticleMarkup(article) {
      const mode = String(article.mode || 'deterministic_template');
      const review = article.editorial_review || {};
      const reviewStatus = String(article.publication_status || review.status || 'approved');
      const reporter = article.reporter_name || article.reporter_id || 'The Front Office';
      const structured = article.structured || {};
      const template = article.template || {};
      const layout = String(template.layout || 'rail').replace(/[^a-z0-9_-]/gi, '');
      const mediaAsset = publicationMediaAsset(article.key);
      const mediaMarkup = publicationMediaMarkup(article.key);
      const summary = [
        structured.lede ? `<p>${escapeHtml(structured.lede)}</p>` : '',
        structured.thesis ? `<p><strong>Thesis:</strong> ${escapeHtml(structured.thesis)}</p>` : '',
        structured.what_changed ? `<p><strong>Changed:</strong> ${escapeHtml(structured.what_changed)}</p>` : '',
        structured.action ? `<p><strong>Question:</strong> ${escapeHtml(structured.action)}</p>` : '',
        structured.counter_evidence ? `<p><strong>Counter-signal:</strong> ${escapeHtml(structured.counter_evidence)}</p>` : ''
      ].filter(Boolean).join('');
      const receipt = (() => {
        const evidenceIds = Array.isArray(structured.evidence_ids) ? structured.evidence_ids.filter(Boolean).map(value => String(value)) : [];
        const sourceIds = Array.isArray(structured.source_ids) ? structured.source_ids.filter(Boolean).map(value => String(value)) : [];
        const fingerprint = article.evidence_fingerprint
          ? `Evidence fingerprint: ${escapeHtml(String(article.evidence_fingerprint).slice(0, 16))}…`
          : 'No article fingerprint recorded; this is the deterministic fallback publication.';
        const evidenceTrace = evidenceIds.length
          ? `<p><strong>Evidence IDs:</strong> ${evidenceIds.map(value => escapeHtml(value)).join(' · ')}</p>`
          : '<p>No article-level evidence IDs were recorded for this fallback. The deterministic read is still linked to the source receipt below.</p>';
        const sourceTrace = sourceIds.length
          ? `<p><strong>Source IDs:</strong> ${sourceIds.map(value => escapeHtml(value)).join(' · ')}</p>`
          : '<p>No source IDs were recorded.</p>';
        const visualDirection = structured.visual_brief
          ? `<p><strong>Visual direction:</strong> ${escapeHtml(structured.visual_brief)}</p>`
          : '';
        const mediaReceipt = mediaAsset
          ? `<p><strong>Media:</strong> ${escapeHtml(mediaAsset.asset_id || 'section art')} · ${escapeHtml(mediaAsset.scope || 'article')} scope · ${escapeHtml(mediaAsset.status || 'available')}. Decorative only.</p>`
          : '';
        const fallbackReason = article.fallback_reason ? ` Fallback: ${escapeHtml(article.fallback_reason)}` : '';
        const deskReview = review.mode === 'llm'
          ? `<p><strong>Desk review:</strong> ${escapeHtml(review.decision || 'hold')}${review.model ? ` · ${escapeHtml(review.model)}` : ''}${review.editor_notes ? ` · ${escapeHtml(review.editor_notes)}` : ''}</p>`
          : '';
        return `<details class="publication-receipt"><summary>Show publication receipt</summary><p>Reporter: ${escapeHtml(reporter)}. Mode: ${escapeHtml(articleModeLabel(mode))}. ${fingerprint}${article.model ? ` Model: ${escapeHtml(article.model)}.` : ''} Source receipt: ${escapeHtml(structured.source_quality || 'unattributed')} (${escapeHtml(String(structured.source_count ?? 0))}).${fallbackReason}</p>${deskReview}${visualDirection}${mediaReceipt}${evidenceTrace}${sourceTrace}<p><a href="#view-data-room">Open the Data Room</a> to inspect the underlying tables, freshness, and limitations.</p></details>`;
      })();
      const actions = reviewStatus === 'approved'
        ? `<div class="publication-actions" aria-label="Explicit article feedback"><button type="button" data-content-interaction="useful" data-artifact-key="${escapeHtml(article.key || '')}">Useful</button><button type="button" data-content-interaction="not_useful" data-artifact-key="${escapeHtml(article.key || '')}">Needs work</button><button type="button" data-content-interaction="evidence_opened" data-artifact-key="${escapeHtml(article.key || '')}">Evidence reviewed</button></div>`
        : '';
      const outcome = reviewStatus === 'approved'
        ? `<div class="publication-outcome" aria-label="Track this article's outcome"><label>Follow-up state<select data-outcome-select="${escapeHtml(article.key || '')}"><option value="open">Track this call</option><option value="confirmed">Confirmed useful</option><option value="missed">Missed or wrong</option><option value="unclear">Unclear / needs more evidence</option></select></label><button type="button" data-content-interaction="outcome" data-artifact-key="${escapeHtml(article.key || '')}">Save outcome</button></div>`
        : '';
      const blocks = Array.isArray(article.content_blocks) ? article.content_blocks : [];
      const bodyMarkup = blocks.length ? publicationContentBlocksMarkup(blocks, template) : articleBody(article.body || '');
      const reviewMarkup = reviewStatus === 'approved'
        ? `<span class="tag publication-review-approved">${review.decision === 'modify' ? 'Editor revised' : 'Editor approved'}</span>`
        : `<div class="publication-review-held"><strong>Held by The Desk Editor</strong><p>${escapeHtml(review.note || 'This report is not printed until its evidence receipt is repaired.')}</p>${Array.isArray(review.errors) && review.errors.length ? `<p>${escapeHtml(review.errors.join('; '))}</p>` : ''}</div>`;
      const reviewBadge = reviewStatus === 'approved'
        ? `<span class="tag publication-review-approved">${review.decision === 'modify' ? 'Editor revised' : 'Editor approved'}</span>`
        : '<span class="tag publication-review-held-label">Held</span>';
      return `<article id="publication-${escapeHtml(article.key || '')}" class="publication-card publication-layout-${layout}" data-article-key="${escapeHtml(article.key || '')}" data-template-id="${escapeHtml(template.template_id || 'evidence-note')}">${mediaMarkup}<div class="publication-meta"><span class="tag">${escapeHtml(articleModeLabel(mode))}</span><span>${escapeHtml(template.label || 'Desk report')}</span><span>${escapeHtml(reporter)}</span>${reviewBadge}</div><h3>${escapeHtml(structured.headline || article.title || 'Desk report')}</h3>${reviewStatus === 'approved' ? `${summary ? `<div class="publication-summary">${summary}</div>` : ''}${bodyMarkup}${actions}${outcome}` : reviewMarkup}${receipt}</article>`;
    }

    function publicationListItemMarkup(item) {
      const raw = String(item || '').replace(/\*\*/g, '').trim();
      if (!raw) return '';
      const detailStart = raw.search(/\s+(?:Evidence|Deep read|Front-office read|Confidence|Guardrail|Source trace):/i);
      const summary = detailStart > 0 ? raw.slice(0, detailStart).trim() : raw;
      const detail = detailStart > 0 ? raw.slice(detailStart).trim() : '';
      const summaryMarkup = escapeHtml(summary);
      const detailMarkup = detail
        ? `<details class="evidence-drawer"><summary>Evidence and guardrails</summary><p class="brief-card-evidence">${escapeHtml(detail)}</p></details>`
        : '';
      return `<li class="publication-list-item"><p>${summaryMarkup}</p>${detailMarkup}</li>`;
    }

    function publicationContentBlocksMarkup(blocks, template) {
      const previewLimit = Math.max(1, Number(template?.list_preview_items || 3));
      const rendered = (blocks || []).map(block => {
        const type = String(block.type || 'paragraph');
        if (type === 'heading') return `<h4 class="article-h">${escapeHtml(block.text || '')}</h4>`;
        if (type === 'list') {
          const items = Array.isArray(block.items) ? block.items : [];
          const visible = items.slice(0, previewLimit).map(publicationListItemMarkup).join('');
          const remaining = items.slice(previewLimit).map(publicationListItemMarkup).join('');
          const more = remaining
            ? `<details class="publication-more"><summary>Show ${items.length - previewLimit} more evidence-backed calls</summary><ul class="article-list">${remaining}</ul></details>`
            : '';
          return `<div class="publication-list-block"><ul class="article-list">${visible}</ul>${more}</div>`;
        }
        if (type === 'paragraph') return `<p class="article-p">${escapeHtml(block.text || '')}</p>`;
        return '';
      }).join('');
      return `<div class="article-body publication-blocks" data-content-block-schema="publication_blocks_v1">${rendered}</div>`;
    }

    function editorialStoryMarkup(story, isLead) {
      const tone = editorialTone(story.story_type);
      const title = story.anchor
        ? `<a href="#${escapeHtml(String(story.anchor))}">${escapeHtml(story.headline || story.entity_name || 'Untitled story')}</a>`
        : escapeHtml(story.headline || story.entity_name || 'Untitled story');
      const score = story.priority_score !== undefined && story.priority_score !== null && String(story.priority_score) !== ''
        ? `<span class="score-tile score-high story-score">${escapeHtml(String(story.priority_score))}</span>`
        : '';
      const confidence = String(story.confidence || 'medium').toLowerCase();
      const chips = [
        story.reporter_name || story.reporter || '',
        story.entity_type === 'manager' ? 'manager profile' : '',
        `confidence ${confidence}`
      ].filter(value => value !== undefined && value !== null && String(value) !== '');
      const claims = (story.claims || []).map(claim => `<div class="claim-item"><span class="claim-label">${escapeHtml(claim.label || 'Claim')}</span><span class="claim-value">${escapeHtml(claim.value || '')}</span></div>`).join('');
      const sources = (story.sources || []).map(source => `<a class="source-link" href="${safeSourceUrl(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.label || 'Source')}</a>`).join('');
      const details = `<details class="evidence-drawer story-details"><summary>Show the evidence</summary><div class="brief-card-evidence">${claims ? `<div class="claim-grid">${claims}</div>` : ''}<p><strong>Watch:</strong> ${escapeHtml(story.watchout || 'Keep the evidence visible.')}</p><p><strong>Evidence:</strong> ${escapeHtml(story.evidence || story.dek || 'No evidence supplied.')}</p>${sources ? `<div class="source-list">${sources}</div>` : ''}</div></details>`;
      return `<article class="editorial-story ${isLead ? 'editorial-lead' : 'editorial-card'} tone-${tone}"><div class="story-kicker-row"><span class="story-kicker">${escapeHtml(story.eyebrow || 'Analyst read')}</span>${score}</div><h3 class="story-title">${title}</h3><p class="story-dek">${escapeHtml(story.dek || '')}</p><p class="story-action"><strong>Read:</strong> ${escapeHtml(story.action || 'Open the evidence before acting.')}</p><div class="story-meta">${chips.map(chip => `<span class="story-chip${chip.startsWith('confidence ') ? ` confidence-${confidence}` : ''}">${escapeHtml(chip)}</span>`).join('')}</div>${details}</article>`;
    }

    function editorialPulse(summary) {
        const metrics = [
        ['priority_reads', 'ranked reads'],
        ['market_consensus', 'market values'],
        ['news_signals', 'news signals'],
        ['manager_profiles', 'manager profiles'],
        ['custom_manager_profiles', 'private profiles']
      ];
      return metrics.map(([key, labelText]) => `<div class="pulse-metric"><strong>${escapeHtml(String(summary[key] ?? 0))}</strong><span>${escapeHtml(labelText)}</span></div>`).join('');
    }

    function editorialHealth(rows) {
      if (!rows.length) return '<li class="note">No source-health receipt is available.</li>';
      return rows.map(row => `<li class="health-row"><span>${escapeHtml(row.label || row.dataset || 'Source')}</span><span class="${row.healthy ? 'health-current' : 'health-limited'}">${escapeHtml(row.status_label || 'Unknown')}</span></li>`).join('');
    }

    function editorialTone(storyType) {
      const type = String(storyType || '').toLowerCase();
      if (type === 'market') return 'market';
      if (type === 'sell') return 'sell';
      if (type === 'hold') return 'hold';
      if (type === 'news') return 'news';
      if (type === 'manager') return 'manager';
      return 'signal';
    }

    function safeSourceUrl(url) {
      const value = String(url || '');
      return value.startsWith('https://') || value.startsWith('http://') ? escapeHtml(value) : '#';
    }

    async function hydrateContentInteractions() {
      if (!manifest.leagueId) return;
      try {
        const response = await fetch(`/api/leagues/${encodeURIComponent(manifest.leagueId)}/content-interactions`);
        if (!response.ok) return;
        const payload = await response.json();
        (payload.interactions || []).filter(item => item.interaction_type === 'outcome').forEach(item => {
          const select = document.querySelector(`[data-outcome-select="${String(item.artifact_key || '').replace(/"/g, '')}"]`);
          const value = item.payload && item.payload.outcome;
          if (select && ['open', 'confirmed', 'missed', 'unclear'].includes(String(value || ''))) select.value = value;
        });
      } catch (error) {
        console.warn('Could not load article outcome state', error);
      }
    }

"""


def inject_editorial_facade(page: str) -> str:
    """Add the issue facade to the generated page without touching its data-room core."""

    page = page.replace("</style>", f"{EDITORIAL_STYLE}\n  </style>", 1)
    page = page.replace(
        '<div class="brand-kicker">Dynasty Command</div>',
        '<div class="brand-kicker">Personal Edition</div>',
        1,
    )
    page = page.replace(
        "<p>Find the market leak, then pretend it was obvious all along.</p>",
        "<p>Your league, edited into a morning read with the data room underneath.</p>",
        1,
    )
    page = page.replace(
        "weekly command surface. Read-only, because the league chat already has enough chaos.",
        "personal edition. Deep data underneath, so every strong opinion can show its work.",
        1,
    )

    start = page.find('    <div id="todays-board" class="view-block">')
    end = page.find('    <div id="decision-board" class="view-block">', start)
    if start >= 0 and end > start:
        page = page[:start] + EDITORIAL_HTML + page[end:]

    page = page.replace("let analysis = {};", "let analysis = {};\n    let editorial = {};", 1)
    page = page.replace("analysis = app.analysis || {};", "analysis = app.analysis || {};\n      editorial = app.editorial || {};", 1)
    page = page.replace(
        "document.getElementById('active-team-label').textContent = teamName;",
        "document.getElementById('active-team-label').textContent = teamName;\n      renderEditorial();",
        1,
    )
    page = page.replace("    function priorityCards(rows) {", f"{EDITORIAL_JS}    function priorityCards(rows) {{", 1)
    return page
