package ro.victorrentea.humanreview

import com.intellij.ide.BrowserUtil
import com.intellij.notification.Notification
import com.intellij.notification.NotificationAction
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.text.StringUtil
import java.io.File
import java.time.Instant

// A card posted to the pull request, opened from the page: the reader came for the
// conversation as much as for the code. The port of vscode-extension/comment-focus.js — as far
// as IntelliJ lets it go.
//
// VS Code's GitHub Pull Requests extension draws the thread in the file, and comment-focus.js
// expands and focuses it. IntelliJ's GitHub plugin draws review threads too, but has no public
// API to expand one on a line: nothing a plugin may call says "open the thread at line 48". So
// this is the honest fallback — land on the lines as usual, then say in a non-modal notification
// that this card is a PR comment, with one action that opens that comment on GitHub. Only when
// the reader clicks it: a browser tab appearing by itself on every reference would be the page
// fighting the reader for the screen.
//
// The answer says which happened, as comment-focus.js's does (`comment: "focused" | "none" |
// …`): here `"notified"` (the notification is up, with the link) or `"none"` (no GitHub URL
// came with the click — a page built before it carried one — so nothing was shown).

/** What a click on a PR comment's card carries: the line GitHub anchored the thread on
 *  (1-based) and the comment's GitHub URL, when the page had one. */
data class CommentAim(val line: Int, val url: String?)

object CommentNotice {
    /** A GitHub comment, a review, or the PR itself — nothing else is handed to the OS browser.
     *  The server checks the same shape before it forwards one; this is the second lock. */
    private val GITHUB = Regex("^https://github\\.com/[^/\\s?#]+/[^/\\s?#]+/pull/\\d+([/?#][^\\s]*)?$")

    fun usable(url: String?): Boolean = url != null && GITHUB.matches(url)

    @Volatile private var last: Map<String, Any?>? = null
    @Volatile private var shown: Notification? = null

    /** What the last comment-carrying open did, for `/editor-state` — VS Code's `lastComment`. */
    fun lastResult(): Map<String, Any?>? = last

    /**
     * After the reference is open: offer the comment's thread on GitHub. `line` is the line
     * GitHub anchored the thread on (1-based). Returns the outcome word. Any thread.
     */
    fun offer(project: Project?, path: String, line: Int, url: String?): String {
        val how = if (usable(url)) "notified" else "none"
        if (how == "notified") {
            shown?.expire()  // one at a time: the previous card's offer is stale now
            val n = NotificationGroupManager.getInstance().getNotificationGroup("Human Review")
                .createNotification("This card is a PR comment", "${StringUtil.escapeXmlEntities(File(path).name)}:$line — the thread is on GitHub.",
                    NotificationType.INFORMATION)
            n.addAction(NotificationAction.createSimpleExpiring("Open on GitHub") { BrowserUtil.browse(url!!) })
            shown = n
            n.notify(project)
        }
        last = linkedMapOf("comment" to how, "path" to path, "line" to line, "url" to url?.takeIf { usable(it) },
            "at" to Instant.now().toString())
        return how
    }

    /** The plugin is going away: its notification's action would call into an unloaded class. */
    fun forget() {
        shown?.expire()
        shown = null
        last = null
    }
}
