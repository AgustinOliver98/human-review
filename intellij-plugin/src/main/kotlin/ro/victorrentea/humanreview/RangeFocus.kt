package ro.victorrentea.humanreview

import com.intellij.openapi.Disposable
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.colors.EditorColors
import com.intellij.openapi.editor.event.CaretEvent
import com.intellij.openapi.editor.event.CaretListener
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.editor.event.EditorFactoryEvent
import com.intellij.openapi.editor.event.EditorFactoryListener
import com.intellij.openapi.editor.event.EditorMouseEvent
import com.intellij.openapi.editor.event.EditorMouseListener
import com.intellij.openapi.editor.event.SelectionEvent
import com.intellij.openapi.editor.event.SelectionListener
import com.intellij.openapi.editor.markup.HighlighterLayer
import com.intellij.openapi.editor.markup.HighlighterTargetArea
import com.intellij.openapi.editor.markup.RangeHighlighter
import com.intellij.openapi.editor.markup.TextAttributes
import com.intellij.openapi.editor.EditorFactory
import com.intellij.openapi.editor.ScrollType
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.FileEditorManagerEvent
import com.intellij.openapi.fileEditor.FileEditorManagerListener
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.ui.ColorUtil

// Land on a *range* of a file, not on a line of it: the range highlighted, everything else
// muted, until the reader takes over the editor.
//
// A Human Review reference is `OwnerListTest.java:49-51` — the reviewer means those three
// lines, and a caret on 49 says nothing about where the quote stops. So the bridge selects
// the range, paints it with a soft background that survives the selection moving, and
// mutes every other line so the eye finds the three lines in a five-hundred-line class
// without hunting.
//
// VS Code fades the rest to 35% opacity. IntelliJ cannot change a text span's opacity, so the
// rest gets a high-layer highlighter whose foreground is the text colour mixed most of the way
// into the background — it wins over syntax colours the same way an "unused symbol" grey does,
// and it is derived from the current scheme, so it is right in a light and a dark theme.
//
// The mute is a statement about the moment of arriving, not a mode the file is left in.
// It goes on the reader's first own move in that editor — a click, a caret move, an edit —
// when another editor becomes the selected one, and when the next reference is opened
// (one focus at a time, replaced, never stacked). Focus moving to the browser with the
// review page keeps it: the reader is reading the page against the code, which is exactly
// when the highlight is wanted.
//
// The pure part (which lines to mute, whether a selection event is the reader's) lives in
// `RangeSpan`, so plain JUnit can test it without an IDE.

/** What moved the caret. VS Code reports it on every selection event; IntelliJ does not, so
 *  MOUSE comes from an `EditorMouseListener` and everything a `CaretListener` sees is OTHER.
 *  (A keyboard listener would also see Cmd+Tab back to the browser — not the reader taking
 *  over the editor — so keys are judged by the guard below like any other caret move.) */
enum class MoveKind { MOUSE, KEYBOARD, OTHER }

object RangeSpan {
    /** How long after the bridge sets its own selection an event from it is still ours.
     *  Opening the file and the explicit selection each move the caret, sometimes a beat
     *  late; nobody clicks inside a file a quarter of a second after it appeared. */
    const val GUARD_MS = 400L

    /** The longest span that gets the treatment. A "range" of thousands of lines is a whole
     *  file, where muting the rest would mute nothing and highlighting it all says nothing. */
    const val MAX_SPAN = 2000

    /** A JSON value as JS's `Number()` reads it: numbers as they are, numeric strings parsed,
     *  anything else not a number. */
    fun num(v: Any?): Double? = when (v) {
        is Number -> v.toDouble()
        is String -> v.trim().toDoubleOrNull()
        else -> null
    }

    private fun int(v: Any?): Int? = num(v)?.takeIf { it % 1.0 == 0.0 && Math.abs(it) < Int.MAX_VALUE }?.toInt()

    /** 1-based `line`..`endLine` → 0-based inclusive `[start, end]`, clamped to the document,
     *  or null when there is no range to focus (no end, a single line, a reversed or absurd
     *  span). */
    fun span(line: Any?, endLine: Any?, lineCount: Int): Pair<Int, Int>? {
        val a = int(line) ?: return null
        val b = int(endLine) ?: return null
        if (a < 1 || b <= a) return null
        if (b - a + 1 > MAX_SPAN) return null
        val last = maxOf(0, lineCount - 1)
        val start = minOf(a - 1, last)
        val end = minOf(b - 1, last)
        return if (end > start) start to end else null
    }

    /** The 0-based inclusive line spans outside `[start, end]` in a document of `lineCount`
     *  lines: at most one above and one below. */
    fun fadeSpans(start: Int, end: Int, lineCount: Int): List<Pair<Int, Int>> {
        val out = mutableListOf<Pair<Int, Int>>()
        if (start > 0) out += 0 to start - 1
        if (end < lineCount - 1) out += end + 1 to lineCount - 1
        return out
    }

    /** Is this selection change the reader's own move? A click or a key always is. Anything
     *  else is ours while it lands on the selection we set, falls inside the guard or inside a
     *  `hold()`, and the reader's after that — arrow keys, Go to Line, a Find jump. */
    fun readerMoved(kind: MoveKind, sinceArmMs: Long, sameAsOurs: Boolean, held: Boolean): Boolean {
        if (kind == MoveKind.MOUSE || kind == MoveKind.KEYBOARD) return true
        if (sameAsOurs || held) return false
        return sinceArmMs >= GUARD_MS
    }
}

/** The IDE half. EDT only: every call here touches an editor's markup and caret. */
object RangeFocus {
    private class Current(
        val editor: Editor,
        val path: String,
        val range: Pair<Int, Int>,
        val highlighters: List<RangeHighlighter>,
        val listeners: Disposable,
        @Volatile var heldUntil: Long = 0,
    )

    @Volatile
    private var current: Current? = null

    /** Drop the current focus, if any: its highlighters off its editor, its listeners gone. */
    fun clear() {
        val c = current ?: return
        current = null
        Disposer.dispose(c.listeners)
        val markup = c.editor.markupModel
        for (h in c.highlighters) runCatching { markup.removeHighlighter(h) }  // the editor was closed
    }

    /** Select, reveal, highlight and mute `line..endLine` (1-based) in `editor`. With no range
     *  (only a line, or a span `span()` rejects) it only clears an earlier focus, so a
     *  single-line open behaves exactly as before. Returns whether a range was focused. */
    fun focus(project: Project, editor: Editor, line: Any?, endLine: Any?): Boolean {
        clear()
        val doc = editor.document
        val (start, end) = RangeSpan.span(line, endLine, doc.lineCount) ?: return false

        val selStart = doc.getLineStartOffset(start)
        val selEnd = doc.getLineEndOffset(end)
        // A range inside a collapsed region (the imports, a folded method) would have the caret
        // pushed out to the fold's start a moment later — which reads as the reader's own move
        // and drops the focus. The reader asked for those lines: they are unfolded.
        val folds = editor.foldingModel
        folds.allFoldRegions.filter { !it.isExpanded && it.startOffset < selEnd && it.endOffset > selStart }
            .takeIf { it.isNotEmpty() }
            ?.let { regions -> folds.runBatchFoldingOperation { regions.forEach { it.isExpanded = true } } }
        editor.caretModel.removeSecondaryCarets()
        editor.caretModel.moveToOffset(selStart)
        editor.selectionModel.setSelection(selStart, selEnd)
        editor.scrollingModel.scrollToCaret(ScrollType.CENTER_UP)
        val armedAt = System.currentTimeMillis()

        // Colours from the editor's own scheme: the highlight is the selection colour mixed
        // well into the background (soft, and still there once the selection moves), the mute
        // is the text colour mixed most of the way into the background.
        val scheme = editor.colorsScheme
        val bg = scheme.defaultBackground
        val highlight = TextAttributes().apply {
            backgroundColor = ColorUtil.mix(bg, scheme.getColor(EditorColors.SELECTION_BACKGROUND_COLOR) ?: bg, 0.45)
        }
        val muted = TextAttributes().apply {
            foregroundColor = ColorUtil.mix(scheme.defaultForeground, bg, 0.62)
        }
        val markup = editor.markupModel
        val hl = markup.addRangeHighlighter(selStart, selEnd, HighlighterLayer.SELECTION - 2,
            highlight, HighlighterTargetArea.LINES_IN_RANGE).apply {
            setErrorStripeMarkColor(highlight.backgroundColor)
            isThinErrorStripeMark = false
        }
        // Above syntax, warnings and errors: a foreground from a higher layer wins.
        val mutes = RangeSpan.fadeSpans(start, end, doc.lineCount).map { (a, b) ->
            markup.addRangeHighlighter(doc.getLineStartOffset(a), doc.getLineEndOffset(b),
                HighlighterLayer.SELECTION - 1, muted, HighlighterTargetArea.EXACT_RANGE)
        }

        val listeners = Disposer.newDisposable("human-review range focus")
        Disposer.register(project, listeners)
        val c = Current(editor, FileDocumentManager.getInstance().getFile(doc)?.path ?: "",
            start to end, listOf(hl) + mutes, listeners)

        fun judge(kind: MoveKind) {
            if (current !== c) return
            val sel = editor.selectionModel
            val sameAsOurs = editor.caretModel.caretCount == 1 &&
                sel.selectionStart == selStart && sel.selectionEnd == selEnd
            val held = System.currentTimeMillis() < c.heldUntil
            if (RangeSpan.readerMoved(kind, System.currentTimeMillis() - armedAt, sameAsOurs, held)) clear()
        }
        editor.caretModel.addCaretListener(object : CaretListener {
            override fun caretPositionChanged(event: CaretEvent) = judge(MoveKind.OTHER)
        }, listeners)
        editor.selectionModel.addSelectionListener(object : SelectionListener {
            override fun selectionChanged(e: SelectionEvent) = judge(MoveKind.OTHER)
        }, listeners)
        editor.addEditorMouseListener(object : EditorMouseListener {
            override fun mousePressed(event: EditorMouseEvent) = judge(MoveKind.MOUSE)
        }, listeners)
        doc.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) { if (current === c) clear() }
        }, listeners)
        // Another editor selected in this project: the focus is about the one it was put on.
        project.messageBus.connect(listeners).subscribe(FileEditorManagerListener.FILE_EDITOR_MANAGER,
            object : FileEditorManagerListener {
                override fun selectionChanged(event: FileEditorManagerEvent) {
                    val now = FileEditorManager.getInstance(project).selectedTextEditor
                    if (current === c && now !== editor) clear()
                }
            })
        EditorFactory.getInstance().addEditorFactoryListener(object : EditorFactoryListener {
            override fun editorReleased(event: EditorFactoryEvent) {
                if (event.editor === editor && current === c) clear()
            }
        }, listeners)

        current = c
        return true
    }

    /** Which range is focused right now (1-based, inclusive), or null — for the bridge's
     *  read-only `/editor-state`, so a caller can check the mute survived what came after. */
    fun active(): Map<String, Any>? {
        val c = current ?: return null
        return linkedMapOf("path" to c.path, "line" to c.range.first + 1, "endLine" to c.range.second + 1)
    }

    /** For the next `ms`, a selection change that is not a click or a key is the bridge's own,
     *  not the reader's. Extends, never shortens; a no-op when nothing is focused. Unused until
     *  the PR comment-thread focus lands (M2), kept so it ports as one piece. */
    fun hold(ms: Long) {
        val c = current ?: return
        c.heldUntil = maxOf(c.heldUntil, System.currentTimeMillis() + ms)
    }
}
