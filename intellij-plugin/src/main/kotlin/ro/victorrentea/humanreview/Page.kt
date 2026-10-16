package ro.victorrentea.humanreview

import com.intellij.ide.BrowserUtil
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.service
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.ui.content.ContentFactory
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser

// The review page *inside* IntelliJ: a "Human Review" tool window holding an embedded Chromium
// (JCEF), beside the code. The port of bridge.js `/open-url`, which shows the page in VS Code's
// Simple Browser for the same reason: the page is read against the code, and a browser on
// another desktop makes the reader swap windows for every reference.
//
// http(s) only — the page's clicks reach the editor by fetching their own origin
// (serve-review.py), so a `file://` page in here would be a page whose links do nothing.
//
// The tool window is declared in plugin.xml (so a dynamic unload removes it, and the browser
// in it with its content's disposer) but stays unavailable — no stripe button — until a page is
// first shown in it. One browser per project window, reused: a second `/open-url` loads the
// new URL in it instead of stacking tabs.
//
// JCEF itself sits behind `PageView`, an application service a test replaces: a headless test
// JVM has no Chromium to start (JBCefApp.isSupported() is false there), so the browser half is
// the one part of the plugin only a real IDE can show.

/** Where a page goes. A service, so a test can record what would have been shown. */
interface PageView {
    /** Whether this IDE can show a page at all: JCEF bundled, enabled, and not headless. */
    fun supported(): Boolean

    /** EDT. Show `url` in `project`'s Human Review tool window; `focus` moves the keyboard
     *  into it, otherwise the reader's caret stays where it was. */
    fun show(project: Project, url: String, focus: Boolean)

    companion object {
        fun get(): PageView = service()
    }
}

class JcefPageView : PageView {
    override fun supported(): Boolean = runCatching { JBCefApp.isSupported() }.getOrDefault(false)

    override fun show(project: Project, url: String, focus: Boolean) {
        val tw = ToolWindowManager.getInstance(project).getToolWindow(PageToolWindowFactory.ID) ?: return
        tw.isAvailable = true
        val cm = tw.contentManager
        val existing = cm.contents.firstNotNullOfOrNull { it.getUserData(BROWSER) }
        if (existing != null && !existing.isDisposed) {
            existing.loadURL(url)
        } else {
            cm.removeAllContents(true)
            val browser = JBCefBrowser.createBuilder().setUrl(url).build()
            val content = ContentFactory.getInstance().createContent(browser.component, "", false)
            content.putUserData(BROWSER, browser)
            // Closing the content, or the tool window going away with the plugin, disposes the
            // browser — a Chromium process left behind would outlive the plugin that started it.
            content.setDisposer(browser)
            cm.addContent(content)
        }
        if (focus) tw.activate(null, true) else tw.show(null)
    }

    companion object {
        private val BROWSER = com.intellij.openapi.util.Key.create<JBCefBrowser>("human-review.browser")
    }
}

/** The tool window's factory: nothing to build up front, and no stripe button until a page has
 *  been shown — most projects never have a review. */
class PageToolWindowFactory : ToolWindowFactory, DumbAware {
    override fun shouldBeAvailable(project: Project) = false
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {}

    companion object {
        const val ID = "Human Review"
    }
}

/** Where a click on the status-bar item sends the page. */
enum class PageTarget { TOOL_WINDOW, BROWSER }

object ReviewPage {
    /** The tool window when the reader wants it there (the default) *and* this IDE can show it;
     *  the OS browser otherwise — a setting this IDE cannot honour is not a dead click. */
    fun target(inIde: Boolean, jcef: Boolean): PageTarget =
        if (inIde && jcef) PageTarget.TOOL_WINDOW else PageTarget.BROWSER

    fun target(): PageTarget = target(HumanReviewSettings.get().pageInIde, PageView.get().supported())

    /** The status-bar click's open. Any thread. */
    fun open(project: Project, url: String) {
        if (target() == PageTarget.BROWSER) return BrowserUtil.browse(url)
        ApplicationManager.getApplication().invokeLater({
            if (!project.isDisposed) PageView.get().show(project, url, focus = true)
        }) { project.isDisposed }
    }

    /** `/open-url`'s answer when the URL is not one a page can be loaded from — bridge.js's words. */
    const val HTTP_ONLY = "http(s) only — an embedded browser cannot load file:// URLs; serve the folder"

    fun isHttp(url: String) = Regex("^https?://", RegexOption.IGNORE_CASE).containsMatchIn(url)
}
