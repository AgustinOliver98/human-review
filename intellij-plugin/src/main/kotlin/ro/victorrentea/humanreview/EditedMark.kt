package ro.victorrentea.humanreview

import com.intellij.openapi.Disposable
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.EditorCustomElementRenderer
import com.intellij.openapi.editor.Inlay
import com.intellij.openapi.editor.markup.HighlighterLayer
import com.intellij.openapi.editor.markup.HighlighterTargetArea
import com.intellij.openapi.editor.markup.RangeHighlighter
import com.intellij.openapi.editor.markup.TextAttributes
import com.intellij.openapi.util.Disposer
import com.intellij.ui.JBColor
import java.awt.Color
import java.awt.Font
import java.awt.Graphics
import java.awt.Rectangle

// A caller that found the file edited since the commit it is quoting says so, on the line the
// reader lands on rather than in a toast elsewhere — the port of review-open.js `markEdited`:
// an amber wash on the line and the sentence in italics after its end. One mark at a time:
// the next one replaces it, as the next VS Code decoration set does.
object EditedMark {
    private val AMBER = JBColor(Color(0xB26B00), Color(0xE0A030))
    private val WASH = JBColor(Color(255, 170, 0, 31), Color(255, 170, 0, 31))

    private var current: Pair<Editor, Disposable>? = null

    /** EDT only. `line0` is 0-based. */
    fun mark(editor: Editor, line0: Int, text: String) {
        clear()
        if (text.isBlank() || editor.document.lineCount == 0) return
        val line = line0.coerceIn(0, editor.document.lineCount - 1)
        val doc = editor.document
        val hl: RangeHighlighter = editor.markupModel.addRangeHighlighter(
            doc.getLineStartOffset(line), doc.getLineEndOffset(line), HighlighterLayer.SELECTION - 3,
            TextAttributes().apply { backgroundColor = WASH }, HighlighterTargetArea.LINES_IN_RANGE,
        ).apply { setErrorStripeMarkColor(AMBER); errorStripeTooltip = text }
        val inlay: Inlay<*>? = editor.inlayModel.addAfterLineEndElement(doc.getLineEndOffset(line), true, Renderer(text))
        val gone = Disposable {
            runCatching { editor.markupModel.removeHighlighter(hl) }
            inlay?.let { Disposer.dispose(it) }
        }
        current = editor to gone
    }

    fun clear() {
        val (_, gone) = current ?: return
        current = null
        runCatching { Disposer.dispose(gone) }  // the editor was closed
    }

    private class Renderer(val text: String) : EditorCustomElementRenderer {
        private fun font(inlay: Inlay<*>): Font =
            inlay.editor.colorsScheme.getFont(com.intellij.openapi.editor.colors.EditorFontType.ITALIC)

        override fun calcWidthInPixels(inlay: Inlay<*>): Int =
            inlay.editor.contentComponent.getFontMetrics(font(inlay)).stringWidth(text) + GAP

        override fun paint(inlay: Inlay<*>, g: Graphics, target: Rectangle, textAttributes: TextAttributes) {
            val editor = inlay.editor
            g.font = font(inlay)
            g.color = AMBER
            g.drawString(text, target.x + GAP, target.y + editor.ascent)
        }
    }

    private const val GAP = 24
}
