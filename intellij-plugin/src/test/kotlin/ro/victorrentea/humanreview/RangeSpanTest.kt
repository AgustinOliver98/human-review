package ro.victorrentea.humanreview

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import ro.victorrentea.humanreview.RangeSpan.GUARD_MS
import ro.victorrentea.humanreview.RangeSpan.MAX_SPAN
import ro.victorrentea.humanreview.RangeSpan.fadeSpans
import ro.victorrentea.humanreview.RangeSpan.readerMoved
import ro.victorrentea.humanreview.RangeSpan.span

// The pure half of RangeFocus.kt, case for case with vscode-extension/test/range-focus.test.js:
// which lines get muted, and which selection events count as the reader taking over.
class RangeSpanTest {
    @Test fun `a 1-based range becomes 0-based inclusive`() {
        assertEquals(48 to 50, span(49, 51, 300))
        assertEquals(48 to 50, span("49", "51", 300))
        assertEquals(48 to 50, span(49.0, 51.0, 300))  // what Gson hands over for a JSON number
    }

    @Test fun `no range - no end, a single line, reversed, not a number`() {
        assertNull(span(49, null, 300))
        assertNull(span(49, 49, 300))
        assertNull(span(51, 49, 300))
        assertNull(span(49, "x", 300))
        assertNull(span(0, 3, 300))
        assertNull(span(1.5, 3, 300))
        assertNull(span(true, 3, 300))
    }

    @Test fun `a span past the cap is not focused`() {
        assertEquals(0 to MAX_SPAN - 1, span(1, MAX_SPAN, 5000))
        assertNull(span(1, MAX_SPAN + 1, 5000))
    }

    @Test fun `clamped to a file that has shrunk`() {
        assertEquals(7 to 9, span(8, 20, 10))
        assertNull(span(12, 20, 10))
    }

    @Test fun `mute covers everything above and below, and nothing of the range`() {
        assertEquals(listOf(0 to 47, 51 to 299), fadeSpans(48, 50, 300))
        assertEquals(listOf(6 to 9), fadeSpans(0, 5, 10))
        assertEquals(listOf(0 to 2), fadeSpans(3, 9, 10))
        assertEquals(emptyList<Pair<Int, Int>>(), fadeSpans(0, 9, 10))
    }

    @Test fun `a click or a key is always the reader`() {
        assertTrue(readerMoved(MoveKind.MOUSE, 0, sameAsOurs = true, held = false))
        assertTrue(readerMoved(MoveKind.KEYBOARD, 0, sameAsOurs = false, held = false))
    }

    @Test fun `our own selection, or anything inside the guard, is not`() {
        assertFalse(readerMoved(MoveKind.OTHER, 5000, sameAsOurs = true, held = false))
        assertFalse(readerMoved(MoveKind.OTHER, GUARD_MS - 1, sameAsOurs = false, held = false))
    }

    @Test fun `a caret move after the guard is the reader`() {
        assertTrue(readerMoved(MoveKind.OTHER, GUARD_MS, sameAsOurs = false, held = false))
    }

    @Test fun `a hold keeps the bridge's own moves from clearing the mute, never a click or a key`() {
        assertFalse(readerMoved(MoveKind.OTHER, 5000, sameAsOurs = false, held = true))
        assertTrue(readerMoved(MoveKind.MOUSE, 5000, sameAsOurs = false, held = true))
        assertTrue(readerMoved(MoveKind.KEYBOARD, 5000, sameAsOurs = false, held = true))
    }
}
