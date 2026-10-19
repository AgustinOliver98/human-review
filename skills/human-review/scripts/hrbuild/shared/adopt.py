"""The "Prompt to get this" buttons: one per adoptable piece, where that piece ends.

Every tab is its own module with its own producer, and several tabs are more than one
mechanism — the Data tab's domain model is drawn by reflection over the classes, its ERD
from the migration scripts, its conceptual model by hand. A reader who likes one of them
wants that one in their own repository, so each piece offers a prompt they paste into
their own coding agent, from the corner of the card that shows it — or, when the piece is
the whole tab, from the right end of the tab's title row.

Minimal on purpose (5 Oct 2026, Victor): the agent on the other end is a smart model with
the repository at hand. It needs to know which piece, where it starts, and that it should
take that piece and nothing else — not a tutorial on how the piece works.

Still minimal, but no longer silent on what a stranger cannot know (10 Oct 2026): one agent
per piece was handed only its prompt in a clone of an unrelated Python/vanilla-JS repo, and
its debrief named what it had to guess. Nearly all of them tripped on the same few things,
now in the shared frame — the start files import siblings, they were written for petclinic's
stack, the trunk is not always `main`, a branch may not touch the piece at all, and whether
to commit. The start lists gained the siblings the agents had to go and find (`puml_diff.py`
behind `puml-diff.sh` cost eight of them the same detour).

Placed after rendering, by anchor, rather than emitted by each renderer: five of these
cards come out of producer scripts (`includeHtml` fragments cached under `.human-review/`),
and a button that needed a producer change would also need every cached fragment
regenerated — the DS audit through Docker, the Tests matrix through a model. Here the
producers stay unaware of the button; the cost is that `PLACES` names the classes of the
cards that carry one, and `test_adopt.py` fails the day one of those stops being emitted.
"""
from __future__ import annotations

import html
import json
import re

from .footer import HOME_URL

#: Not the 📋 the copy commands wear: this one is a message for an agent, not a command.
ROBOT = "\U0001F916"   # 🤖

PETCLINIC = "https://github.com/victorrentea/petclinic/blob/main/petclinic-backend/"

#: piece → (what the button gets you, where it starts). A path is under
#: `skills/human-review/`; a URL is a reference implementation in another repository.
PIECES: dict[str, tuple[str, str]] = {
    "review.assumed": (
        "the coder's assumptions listed for a human reviewer — every place the ticket did "
        "not decide, the reading the coding agent chose, how sure it was, and the "
        "alternative it did not take",
        "reference/review-points.md, scripts/authoring-sessions.py, scripts/review-points.py, "
        "scripts/hrbuild/tabs/review.py"),
    "review.open": (
        "an AI code review of the branch that leaves its open issues for a human, each "
        "with its severity, the reviewer that raised it and the code it is about",
        "reference/review-prompt.md, reference/review-points.md, scripts/review-points.py, "
        "scripts/review_points_schema.py"),
    "review.fixed": (
        "an auto-fix round after that review: the issues it accepted, fixed in one commit "
        "and shown with their diffs",
        "reference/review-prompt.md, scripts/rerun-review.py, scripts/review-points.py, "
        "scripts/review_points_schema.py"),
    "behaviour": (
        "a narrated film of the feature working, recorded by a Playwright script, with its "
        "captions as a clickable transcript beside the player",
        "reference/film-prompt.md, reference/feature-script.md, "
        "scripts/record-feature-video.sh, scripts/hrbuild/tabs/demo.py, "
        "scripts/hrbuild/assets/caption.js"),
    "behaviour.seed": (
        "named datasets (DB fixtures) the running app can be reset to with one click, each "
        "one's tables shown in place so two of them can be compared",
        "scripts/dataset_view.py, scripts/hrbuild/assets/dataset-view.js, "
        "scripts/hrbuild/shared/fixtures.py"),
    "api": (
        "the REST contract at the merge-base against the branch, as a visual OpenAPI diff "
        "with a breaking-change verdict", "scripts/openapi-visual-diff.py, "
        "scripts/openapi-compat.py, scripts/schema_tree.py"),
    "diagram.domain": (
        "the domain-model class diagram generated from your domain classes by Java "
        "reflection, committed as PlantUML and diffed base against branch",
        PETCLINIC + "src/test/java/victor/training/petclinic/guardrail/"
        "DomainModelExtractorTest.java, " + PETCLINIC + "src/test/java/victor/training/"
        "petclinic/guardrail/DomainModelExtractor.java, scripts/puml-diff.sh, "
        "puml-diff/puml_diff.py"),
    "diagram.db": (
        "the ERD generated from your DB migration scripts, committed as PlantUML and "
        "diffed base against branch",
        PETCLINIC + "docs/scripts/db/db_schema_to_puml.py, scripts/puml-diff.sh, "
        "puml-diff/puml_diff.py, scripts/hrbuild/shared/diagrams.py"),
    "diagram.drawio": (
        "the hand-drawn draw.io {title} diagram, checked against the code by a test and "
        "diffed base against branch",
        PETCLINIC + "src/test/java/victor/training/petclinic/guardrail/"
        "ConceptualModelDiagramTest.java, " + PETCLINIC + "src/test/java/victor/training/"
        "petclinic/guardrail/DeploymentDiagramTest.java, " + PETCLINIC + "src/test/java/"
        "victor/training/petclinic/guardrail/DrawioDiagram.java, scripts/drawio-diff.py"),
    "diagram.packages": (
        "the package diagram, kept as PlantUML, enforced on the code by ArchUnit and "
        "diffed base against branch", PETCLINIC + "src/test/java/victor/training/petclinic/"
        "guardrail/PackagesArchTest.java, scripts/puml-diff.sh, puml-diff/puml_diff.py"),
    "diagram.frontend": (
        "the frontend's folders and who imports whom, kept as PlantUML, enforced on the "
        "code by a node:test that reads every import, and diffed base against branch",
        "https://github.com/victorrentea/petclinic/blob/main/petclinic-frontend/scripts/"
        "packages-arch.test.mjs, scripts/puml-diff.sh, "
        "puml-diff/puml_diff.py"),
    "diagram.modules": (
        "the module graph generated from your build files, committed as PlantUML and "
        "diffed base against branch",
        PETCLINIC + "docs/scripts/mavenmodules/maven_modules_to_puml.py, scripts/puml-diff.sh, "
        "puml-diff/puml_diff.py"),
    "diagram.c2": (
        "the C4 container (C2) diagram projected from traced test runs — every arrow an "
        "observed call — diffed base against branch",
        "scripts/c2-from-sequence.py, scripts/puml-diff.sh, puml-diff/puml_diff.py"),
    "diagram.c4": (
        "the C4 views of your Structurizr DSL workspace, rendered by Structurizr itself "
        "(light and dark) and compared base against branch",
        "scripts/structurizr-views.py, scripts/hrbuild/shared/c4.py"),
    "diagram": (
        "the {title} diagram, kept in the repository as PlantUML and diffed base against "
        "branch", "scripts/puml-diff.sh, puml-diff/puml_diff.py, puml-diff/seq_puml_diff.py"),
    "requirements": (
        "the ticket's requirements mapped to the tests that prove each one, side by side, "
        "with every test that runs the changed lines",
        "reference/matrix-prompt.md, scripts/rerun-model.py, scripts/semcov.py, "
        "scripts/testcov.py"),
    "sequence": (
        "sequence diagrams drawn from traced test runs, each beside the test that drew it",
        "scripts/hrbuild/shared/genseq.py, scripts/puml-diff.sh, puml-diff/seq_puml_diff.py"),
    "city": ("a 3D Code City of the classes, coloured by what the branch changed",
             "scripts/regenerate-codecity.sh, https://github.com/victorrentea/code-city"),
    "dsaudit": ("every UI screen at the base against the branch, audited for controls from "
                "outside the design system", "scripts/ds-audit.py"),
    "complexity": ("the cognitive complexity of every entry point the branch touched, "
                   "before and after", "scripts/endpoint-complexity-delta.py"),
    "logging": ("every log statement the branch added, found by syntax-aware search and "
                "checked for privacy problems", "scripts/logextract.py"),
    "owners": ("a check that CODEOWNERS still covers every file the branch touched, and "
               "who must approve it", "scripts/codeowners-check.py"),
    "cost": ("what writing and reviewing the change cost in model tokens",
             "scripts/review-cost.py, scripts/harness_cost.py, scripts/authoring-sessions.py"),
}


#: The (i) beside every pill: what the reader is looking at, before they copy a prompt for
#: it (7 Oct 2026, Victor: "whoever goes to click Prompt to get this should first
#: understand what they're looking at"). Worded as Victor explained each tab at Devoxx
#: Belgium the same day, and kept brief ("be brief in the details you give in the (i)
#: modals"): one sentence per bullet (8 Oct 2026), then at most one tiny example. Static, the same on every PR,
#: so no line may state what only one PR shows; an example is marked "e.g.".
#: Persona-reviewed 8 Oct 2026 by four impatient backend devs (Spring, Quarkus, Node): every
#: box ends with what to look for, and "how it was made" stays a clause, never its own line.
#: Keyed by piece, or by "piece:Card title" when one piece covers unlike cards (the two
#: draw.io diagrams). `move`: the tab's own "how this was made" line, a CSS selector,
#: moved into the box so the visible page stays calm (its counts stay live).
#: `li` lines, then `ex` (one muted example line) or `code` (a tiny snippet; HTML).
EXPLAIN: dict[str, dict[str, object]] = {
    'review.assumed': {
        "li": [
            'Where the ticket was vague, the coder guessed, with how sure it was.',
            'Read these first: a wrong guess is a wrong feature.',
            'Confirm or reject each one with whoever wrote the ticket.',
        ],
        "ex": 'e.g. "link a vet to a visit": can the vet be left empty?',
    },
    'review.open': {
        "li": [
            'A quorum of adversarial AI reviewers criticised the code.',
            'These the coder refused or left open.',
            'You decide, top first: <b>must look</b> › <b>worth a look</b> › <b>nit</b>.',
            'The GitHub icon opens the PR comment; the title or IDE icon opens the line in your IDE.',
        ],
    },
    'review.fixed': {
        "li": [
            'What the AI reviewers raised and the coder already fixed, one diff each.',
            'Skim them: stop only at a fix that changed behaviour.',
        ],
    },
    'behaviour': {
        "li": [
            'A short film of the feature on the real app: start here on a PR you never saw.',
            'Its script and narration are written by an AI.',
            'Check it does what the ticket asked.',
            'Click a transcript line to jump there.',
            '<b>Running app</b>: this build in Docker, to try yourself; Start says which step it is on.',
        ],
    },
    'behaviour.seed': {
        "li": [
            'The rows put in the demo database before you try the app.',
            '<b>Default</b> is the seed: the app inserts it into the database when it first boots.',
            'Any other fixture is a dataset of its own, built on an empty DB when you press its <b>Seed</b>.',
            'Each <b>Seed</b> empties every table and reloads that dataset, wiping what you typed.',
            'Open a fixture to see its tables.',
            'The file name on the right opens the SQL that holds the fixture\'s rows.',
        ],
    },
    'api': {
        "li": [
            'The OpenAPI contract, main vs this branch, diffed by oasdiff.',
            '<b>Breaking</b>: a client of main can fail.',
            'One DTO change can break many endpoints.',
            'For each break, ask who calls it and if they were updated.',
        ],
        "code": (
            '<span class="c">e.g. GET /api/owners/1</span>\n'
            '<span class="c">main:  </span>{ "name": "Leo" }\n'
            '<span class="c">branch:</span>{ "firstName": "Leo" }   <span class="p">breaking</span>'
        ),
    },
    'diagram.domain': {
        "li": [
            'The entities, generated from the Java classes, not drawn by AI.',
            'Green = added by this PR.',
            'Check each new link: wanted, and <code>1─*</code> the right way round?',
            '<b>✓ Generated from …</b>: the source it is redrawn from; click for the generator.',
            '<b>changed</b> / <b>unchanged</b>: whether this branch moved the drawing.',
        ],
        "ex": 'e.g. <code>Owner 1─* Pet 1─* Visit</code>',
    },
    'diagram.db': {
        "li": [
            'The real tables: the migrations run on an empty DB, then read back.',
            'Green = added by this PR.',
            'Look for a new FK without an index, or NOT NULL on a table that has rows.',
            '<b>✓ Generated from …</b> beside <b>changed</b>: its source; click for the generator.',
        ],
    },
    'diagram.drawio': {
        "li": [
            'The same concepts, laid out by hand in draw.io, so they stay where you remember them.',
            'A unit test checks the boxes and lines against the code.',
            'A new line is a new dependency: is it wanted?',
            '<b>✓ Tested vs …</b> after the title: hover for the test and what it checks; click opens it.',
        ],
        "ex": 'e.g. a red line: the test wants it, so the author draws it.',
    },
    'diagram.drawio:Deployment': {
        "li": [
            'What runs where, drawn by hand in draw.io.',
            'A test fails on any call the e2e tests made that the drawing lacks.',
            '<b>✓ Tested vs traces</b> after the title names that test; click to open it.',
        ],
        "ex": 'e.g. red dashed: called in the tests, missing from the drawing.',
    },
    'diagram.packages': {
        "li": [
            'The Java packages and who depends on whom.',
            '<a href="https://www.archunit.org/" target="_blank" rel="noopener noreferrer">'
            'ArchUnit</a>, a test library, fails the build on an import the drawing lacks.',
            'A new arrow is new coupling: ask why.',
            '<b>Green bar</b> in a box = its share of the lines this PR added here.',
            'Hover a box for its changed files; click one for its diff.',
            '<b>✓ ArchUnit-tested vs code</b> after the title: click it to open that test.',
        ],
        "ex": 'e.g. <code>..domain</code> → <code>..rest</code>: not drawn, so a test fails.',
    },
    'diagram.frontend': {
        "li": [
            'The frontend folders and who imports whom.',
            'A test reads every <code>import</code> and fails on one the drawing lacks.',
            'A new arrow is new coupling: ask why.',
            '<b>Green bar</b> in a box = its share of the lines this PR added here.',
            'Hover a box for its changed files; click one for its diff.',
            '<b>✓ Tested vs code</b> after the title names that test; click to open it.',
        ],
        "ex": 'e.g. <code>parts</code> → <code>owners</code>: not drawn, so a test fails.',
    },
    'diagram.modules': {
        "li": [
            'The Maven modules and who depends on whom, from <code>mvn dependency:tree</code>.',
            'A new arrow or a cycle between modules: ask why.',
            '<b>Green bar</b> in a box = its share of the lines this PR added here.',
            'Hover a box for its changed files; click one for its diff.',
            '<b>✓ Generated from …</b>: the source it is redrawn from; click for the generator.',
        ],
    },
    'diagram.c2': {
        "li": [
            'C4 level 2: the apps and databases, and who calls whom.',
            'Drawn by a script from the e2e test traces, not by AI: every arrow really happened.',
            'A new arrow = a new runtime dependency.',
            '<b>changed</b>: this branch moved its picture; <b>Diff</b> shows how.',
        ],
        "ex": 'e.g. Browser → Backend: <code>GET /api/owners</code>.',
    },
    'diagram.c4': {
        "li": [
            "A C4 view, drawn from the repo's Structurizr <code>.dsl</code>.",
            'C1 = users and systems, C2 = apps and DBs, C3 = parts of one app.',
            '<b>✓ ArchUnit-tested vs code</b>: a test checks it; else the line under it says hand-kept.',
        ],
    },
    'diagram': {
        "li": [
            'A PlantUML diagram kept in the repo.',
            'The badge says whether this PR changed it.',
            '<b>✓</b> after it: a test checks it, or a script generates it; click to open that.',
        ],
    },
    'requirements': {
        "li": [
            'Left: the ticket; right: every test that ran a line this PR changed (blue shield).',
            '<b>green</b> = proven · <b>orange</b> = partly · <b>red</b> = no test; AI-matched, may be wrong.',
            'Name colour = kind: E2E and API weigh most, they prove the feature, not one method.',
            'Click a sentence: a line to each test covering it; <b>▲ ▼</b> = more scrolled away.',
            '<b>− ✍️ +</b> before a total: deleted, edited, new tests; <b>Show all tests</b> adds the rest.',
            'Dot: the DB data a test starts on; grey = Default, hollow = uses none of its rows.',
        ],
    },
    'sequence': {
        "move": 'details.seqhow',
        "li": [
            'One per test with the tracing tag, or that this branch wrote or edited.',
            'HTTP calls, SQL with parameters, calls across services and modules.',
            'Diff: green/red = a call this PR added/removed; its tx box and activation bar tinted.',
            'Click <b>⊕</b> for the SQL or JSON; <b>values</b> fills in each <b>?</b>.',
            'An IDE logo on a call opens that method in the IDE whose logo is green, top right.',
            'The dot before the file name is the DB fixture the test starts from: grey = Default.',
        ],
        "code": (
            'GET /api/owners\n'
            '  → OwnerRepository.findByLastNameStartingWith\n'
            '  → select pets, select visits   <span class="p">per owner ← N+1</span>'
        ),
    },
    'city': {
        "li": [
            'One building per class: area = lines of code, height = how many ifs.',
            'Arrows up = grew in this PR.',
            'Use it on a huge PR: where is the code growing?',
        ],
    },
    'dsaudit': {
        "li": [
            'Every screen, main vs this branch on the same data: a pixel-level visual diff.',
            "A script flags controls that aren't from the app's own components.",
            'Open the changed screens: is each change wanted?',
            '✅ judged fine · ⚠️ a gap · ⚪ changed, but no control to judge.',
        ],
        "ex": 'e.g. a home-made combo box, or an inline <code>style=</code>.',
    },
    'complexity': {
        "move": 'p.cx-lede',
        "li": [
            'Cognitive complexity per endpoint: its whole call graph, walked and summed.',
            'Nesting is what costs: each level adds one.',
            'Green = added by this PR; hover a number for what it counts.',
            'Watch the + per endpoint, not the total.',
        ],
        "code": (
            'for (Owner o : owners) {            <span class="p">// +1</span>\n'
            '  if (o.getPets().isEmpty()) {      <span class="p">// +2  nested once</span>\n'
            '    for (Visit v : visits) {}       <span class="p">// +3  nested twice</span>'
        ),
    },
    'logging': {
        "move": 'p.tabsub',
        "li": [
            'Every log line this PR adds or changes.',
            'Check: right level?',
            'No personal data?',
            'Enough context to debug?',
        ],
        "code": (
            '<span class="c">e.g. ✗</span> log.info("Saved {}", owner);  <span class="p">// phone, address</span>'
        ),
    },
    'owners': {
        "li": [
            'Who must approve before merge, per <code>CODEOWNERS</code>, for the files touched.',
            'Change the contract (API, DB), meet the tech leads.',
            'Touch the guardrails (build, CI), meet the elders.',
        ],
    },
    'cost': {
        "li": [
            'What this PR cost in tokens, per stage: implementation, review, auto-fixes, this guide.',
            '$ at API list price, not your subscription.',
            'Time = model thinking + tools (builds, tests).',
        ],
        "ex": 'e.g. on one PR: implementation $15 · review $5 · auto-fixes $9 · this guide $0.30.',
    },
}

#: A diagram card's piece, read off its head (title and source file), first match wins.
DIAGRAM_KINDS = (
    # First: a Structurizr card's head names a `.dsl` whose file name may say C2 too.
    ("diagram.c4", re.compile(r"\.dsl\b|\bStructurizr\b", re.I)),
    ("diagram.drawio", re.compile(r"\.drawio\b", re.I)),
    ("diagram.domain", re.compile(r"domain\s*model", re.I)),
    ("diagram.db", re.compile(r"\bDB\b|\bERD\b|\bschema\b", re.I)),
    ("diagram.c2", re.compile(r"\bC2\b", re.I)),
    ("diagram.frontend", re.compile(r"\bfrontend\b", re.I)),
    ("diagram.modules", re.compile(r"\bmodules?\b", re.I)),
    ("diagram.packages", re.compile(r"\bpackages?\b", re.I)),
)

#: tab → where its buttons go: (piece, how, the opening tag it anchors on, which match).
#: The rule (5 Oct 2026, Victor): a prompt about ONE card sits inside that card, in its
#: bottom-right; a tab that holds one piece of knowledge, one generation, has its prompt
#: on the right of that tab's title. So: `in` — a row at the end of that card, inside its
#: border; `title` — the anchor is the tab's first row (its `h2.tabtitle`, or whatever row
#: opens a tab that has none: the API verdict band, the UX audit's count line, the Tests
#: key over the card), and it becomes a flex row with that row on the left and the pill on
#: the right (a row too long to share its line wraps its own text beside the pill); `col` — under it
#: in a column of its own (the Demo's transcript, beside the player); `upto` — a row
#: closing the region that starts at the anchor and runs to the next Round kicker (the
#: Review tab's three piles). Piece None is a diagram card, whose piece is read off its
#: head. A tab whose anchor is missing gets one row at the end of the panel, so a renamed
#: class costs placement, never the button.
DIAGRAM_CARD = r'<div class="diagram(?![^"]*\bdgm-bare\b)[^"]*"'
PLACES: dict[str, tuple[tuple[str | None, str, str | None, str | None], ...]] = {
    "review": (("review.assumed", "upto", r'<h2 id="assumed"', "first"),
               ("review.open", "upto", r'<h2 id="first"', "first"),
               ("review.fixed", "upto", r'<h2 id="fixed"', "first")),
    "behaviour": (("behaviour", "col", r'<ol class="transcript"', "first"),),
    "api": (("api", "title", r'<div class="apiverdict\b', "first"),),
    "data": ((None, "in", DIAGRAM_CARD, "all"),),
    "packages": ((None, "in", DIAGRAM_CARD, "all"),),
    "requirements": (("requirements", "title", r'<p class="rm-cats"', "first"),),
    "sequence": (("sequence", "title", r'<h2 class="tabtitle\b', "first"),),
    "city": (("city", "title", r'<h2 class="tabtitle\b', "first"),),
    "dsaudit": (("dsaudit", "title", r'<h2 class="tabtitle\b', "first"),),
    "complexity": (("complexity", "title", r'<h2 class="tabtitle\b', "first"),),
    "logging": (("logging", "title", r'<h2 class="tabtitle\b', "first"),),
    "owners": (("owners", "title", r'<h2 class="tabtitle\b', "first"),),
    "cost": (("cost", "title", r'<h2 class="tabtitle\b', "first"),),
}

# One token of markup: a comment, a whole script/style element (whose text may say `<div`
# without opening one), or a tag — attribute values may hold a `>`.
_TAG = re.compile(r'<!--.*?-->|<(script|style)\b.*?</\1\s*>'
                  r'|<(/?)([a-zA-Z][\w-]*)(?:"[^"]*"|\'[^\']*\'|[^\'">])*>', re.S | re.I)


def _close(doc: str, start: int) -> tuple[int, int] | None:
    """Where the element opening at `start` closes: (start, end) of its closing tag."""
    first = _TAG.match(doc, start)
    if not first or not first.group(3):
        return None
    name, depth = first.group(3).lower(), 1
    for m in _TAG.finditer(doc, first.end()):
        if (m.group(3) or "").lower() != name or m.group(0).endswith("/>"):
            continue
        depth += -1 if m.group(2) else 1
        if not depth:
            return m.start(), m.end()
    return None


#: The one-line captions a diagram card can end on: its legend, or a producer's note.
_CAPTION = re.compile(r'<p class="(?:cmlegend|sub dgm-stale)\b[^"]*"')


def _last_caption(doc: str, start: int, end: int) -> int | None:
    """Where the caption that closes the card [start, end) opens, if it ends on one:
    the pill then sits at the right end of that line (Victor, 6 Oct 2026) instead of on
    a row of its own under it."""
    last = None
    for m in _CAPTION.finditer(doc, start, end):
        last = m
    if not last:
        return None
    span = _close(doc, last.start())
    return last.start() if span and not doc[span[1]:end].strip() else None


def adopt_prompt(piece: str, title: str = "") -> str | None:
    """The prompt a button copies, or None for a piece with nothing to get."""
    if piece not in PIECES:
        return None
    what, start = PIECES[piece]
    what = what.format(title=title or "this")
    starts = ", ".join(s if s.startswith("http") else f"skills/human-review/{s}"
                       for s in start.split(", "))
    return (f"Get {what} into this repository — one piece of the review page of "
            f"{HOME_URL} (branch main). Start from {starts}, and what they import. "
            "They were written for a Java/Spring + Angular project: port the idea and "
            "rewrite what only fits that stack. Take only that piece. Run it on the "
            "current branch against its merge-base with this repository's trunk, and "
            "show me the result — if the branch does not touch what this piece shows, say "
            "so and show it on a recent commit that does. Leave the changes uncommitted.")


#: What the green fill in a package/module box means, left of the pill on a card that has one
#: (Victor, 18 Oct 2026: "it's not clear what the progress bar means"). The swatch is a
#: box drawn like the diagram's own, a third filled, so the legend looks like the thing.
IMPACT_LEGEND = (
    '<span class="impact-legend" data-tip="Hover a box for its changed files">'
    '<svg viewBox="0 0 30 14" aria-hidden="true">'
    '<rect x=".5" y=".5" width="29" height="13" rx="2" fill="var(--dgm-box-accent)" '
    'stroke="var(--dgm-line-accent)"/>'
    '<rect x=".5" y=".5" width="11" height="13" rx="2" fill="var(--dgm-diff-add)" '
    'fill-opacity=".45"/></svg>'
    '<span><b>green fill</b> = the box\'s share of the lines this PR added</span></span>')


def adopt_html(piece: str, title: str = "", how: str = "in", page: bool = False,
               explain: bool = True, lead: str = "") -> str:
    prompt = adopt_prompt(piece, title)
    if not prompt:
        return ""
    # A pill on the tab's title row (`page`) is about the whole tab; every other placement,
    # a diagram card's included, is about a smaller area of a screen and keeps the short label.
    label = "Prompt to get this page" if page else "Prompt to get this"
    return (f'<div class="adoptline adopt-{how}">{lead}<button type="button" class="adopt copycmd" '
            f'data-piece="{html.escape(piece)}" data-copy="{html.escape(prompt, quote=True)}" '
            'data-say="Copied — paste it to your coding agent" '
            'data-tip="Copy a prompt for your coding agent to get this into your project">'
            f'{ROBOT} {label}</button>{explain_button(piece, title) if explain else ""}</div>')


def explain_key(piece: str, title: str = "") -> str | None:
    """The `EXPLAIN` entry for a piece's card, or None when there is none."""
    for key in (f"{piece}:{title}", piece):
        if key in EXPLAIN:
            return key
    return None


def explain_button(piece: str, title: str = "") -> str:
    """The blue (i), always right after the pill it explains. `explain.js` opens its box on click."""
    key = explain_key(piece, title)
    if not key:
        return ""
    return (f'<button type="button" class="hrx-i" aria-pressed="false" '
            f'data-explain="{html.escape(key, quote=True)}" aria-label="What am I looking at?" '
            'data-tip="What am I looking at?"></button>')


def explain_data() -> str:
    """`EXPLAIN` as the JSON block `explain.js` reads; `</` escaped so no text can close it."""
    return ('<script type="application/json" id="hr-explain">'
            + json.dumps(EXPLAIN, ensure_ascii=False).replace("</", "<\\/") + "</script>")


def place_prompts(tid: str, body: str) -> str:
    """The panel body with every one of its pieces' buttons in place."""
    places = PLACES.get(tid)
    if not places:
        return body
    edits = []                      # (at, cut_to, text): applied back to front
    for piece, how, anchor, which in places:
        hits = list(re.finditer(anchor, body))
        hits = hits if which == "all" else hits[-1:] if which == "last" else hits[:1]
        taken = []                  # a card inside a card already given its button
        for hit in hits:
            if any(a < hit.start() < b for a, b in taken):
                continue
            if how == "upto":
                nxt = re.compile(r'<p class="pileround"').search(body, hit.end())
                at = nxt.start() if nxt else len(body)
                edits.append((at, at, adopt_html(piece, how="after")))
                continue
            span = _close(body, hit.start())
            if not span:
                continue
            taken.append((hit.start(), span[1]))
            name, title = piece, ""
            if piece is None:       # a diagram card: its piece is read off its head
                # The whole head, balanced: since the action buttons moved into it
                # (16fe638) it nests a `rerun-acts` div before the file name, and a
                # non-greedy `.*?</div>` stopped there — a draw.io card then lost its
                # `.drawio` and got the PlantUML prompt and explainer.
                card = body[hit.start():span[0]]
                h0 = card.find('<div class="head">')
                h1 = _close(card, h0) if h0 >= 0 else None
                inner = card[h0 + len('<div class="head">'):h1[0]] if h1 else ""
                text = html.unescape(re.sub(r"<[^>]+>", " ", inner))
                b = re.search(r"<b>(.*?)</b>", inner, re.S)
                title = html.unescape(re.sub(r"<[^>]+>", "", b.group(1))).strip() if b else ""
                name = next((k for k, rx in DIAGRAM_KINDS if rx.search(text)), "diagram")
                # The (i) rides the pill at the card's foot, like every other card's (Victor,
                # 14 Oct 2026). From 8 Oct it sat in the header after the source file name,
                # a card's height away from the button it explains.
            lead = (IMPACT_LEGEND if piece is None and 'class="pkg-impact"' in card
                    else "")
            if how == "in":
                cap = _last_caption(body, hit.start(), span[0])
                if cap:             # the card ends on a caption line: the pill shares it
                    edits.append((cap, cap, '<div class="adoptfoot">'))
                    edits.append((span[0], span[0],
                                  adopt_html(name, title, "title", lead=lead) + "</div>"))
                else:
                    edits.append((span[0], span[0], adopt_html(name, title, "in", lead=lead)))
            elif how == "title":
                edits.append((hit.start(), hit.start(), '<div class="adopthead">'))
                edits.append((span[1], span[1], adopt_html(
                    name, title, "title", page=piece is not None) + "</div>"))
            elif how == "col":
                edits.append((hit.start(), hit.start(), '<div class="adoptcol">'))
                edits.append((span[1], span[1], adopt_html(name, title, "after") + "</div>"))
            else:
                edits.append((span[1], span[1], adopt_html(name, title, how)))
    if not edits:
        # The anchor moved: the button loses its place, not its existence.
        first = next(p for p, *_ in places)
        return body + (adopt_html(first, how="end") if first else "")
    for at, to, text in sorted(edits, key=lambda e: e[0], reverse=True):
        body = body[:at] + text + body[to:]
    return body
