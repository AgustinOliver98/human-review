package ro.victorrentea.humanreview

import com.google.gson.GsonBuilder
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.intellij.ide.impl.ProjectUtil
import com.intellij.ide.projectView.ProjectView
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.ApplicationNamesInfo
import com.intellij.openapi.application.ModalityState
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.service
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.project.Project
import com.intellij.openapi.startup.ProjectActivity
import com.intellij.openapi.vfs.LocalFileSystem
import com.intellij.openapi.wm.IdeFocusManager
import com.intellij.openapi.wm.ToolWindowId
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.util.concurrency.AppExecutorUtil
import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.awt.KeyboardFocusManager
import java.lang.ref.WeakReference
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.URI
import java.net.URLDecoder
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicBoolean

// The loopback listener a Human Review page reaches IntelliJ through.
//
// A review page is full of `path:line` references, and a reviewer reading one wants to land
// in the class — in the project window that has *that* checkout open, on the reviewed commit.
// The page cannot do it itself: an `idea://` link goes to whichever project the IDE picks, and
// inside an embedded browser a sandboxed iframe cannot hand a custom scheme to the OS at all.
// What the page *can* do is fetch its own origin, so the server it was loaded from
// (serve-review.py) calls this.
//
// Unlike VS Code — one extension host, so one listener, per window — IntelliJ runs every
// project window in one JVM. So there is ONE listener per IDE process (port 0: the OS picks a
// free one), published as `{app:"idea", port, token, pid}` under ~/.human-review/ide/
// (Registry.kt). `/ping` answers with the folders of *every* open project, so the caller's
// longest-prefix routing works across windows, and the bridge then picks the project inside
// the process by the same rule (Folders.kt).
//
// The same wire protocol as vscode-extension/bridge.js, route for route; the routes that need
// the reviewed-version check, the diff view and the embedded browser answer 501 until M2/M3.

@Service(Service.Level.APP)
class HumanReviewBridge : Disposable {
    private val log = thisLogger()
    private val started = AtomicBoolean(false)
    private val gson = GsonBuilder().serializeNulls().disableHtmlEscaping().create()

    @Volatile private var server: HttpServer? = null
    @Volatile private var registryFile: Path? = null
    @Volatile private var token: String? = null
    private var shutdownHook: Thread? = null

    /** The project the last `/open-file` or `revealInExplorer` acted on, for a bare
     *  `focusWindow` right after it: serve-review.py reveals, then raises "the window" with no
     *  uri — and in a process hosting several projects, the window is the one just acted on. */
    @Volatile private var lastTarget: Pair<WeakReference<Project>, Long>? = null

    fun start() {
        // One listener per IDE process, however many projects are open.
        if (!started.compareAndSet(false, true)) return
        try {
            val http = HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0)
            val secret = Token.mint()
            token = secret
            http.createContext("/") { ex -> handle(ex) }
            // A pool, not the server's single dispatcher thread: an `/open-file` waiting on an
            // EDT busy behind a modal dialog must not hold up `/ping`.
            http.executor = AppExecutorUtil.getAppExecutorService()
            http.start()
            server = http
            val pid = ProcessHandle.current().pid()
            registryFile = Registry.publish(Registry.DIR, http.address.port, secret, pid)
            // `dispose()` runs on a normal exit; a `kill <pid>` skips services but still runs
            // JVM shutdown hooks, and a stale entry with a dead port is one more thing every
            // caller has to time out on.
            shutdownHook = Thread { registryFile?.let { runCatching { Files.deleteIfExists(it) } } }
                .also { Runtime.getRuntime().addShutdownHook(it) }
            log.info("human-review bridge listening on 127.0.0.1:${http.address.port}")
        } catch (e: Exception) {
            log.warn("human-review: listener failed", e)
        }
    }

    override fun dispose() {
        server?.stop(0)
        server = null
        registryFile?.let { runCatching { Files.deleteIfExists(it) } }
        registryFile = null
        shutdownHook?.let { runCatching { Runtime.getRuntime().removeShutdownHook(it) } }
        shutdownHook = null
    }

    // ------------------------------------------------------------------ plumbing

    private class HttpError(val code: Int, val body: Map<String, Any?>) : Exception()

    private fun send(ex: HttpExchange, code: Int, body: Any) {
        val data = gson.toJson(body).toByteArray(Charsets.UTF_8)
        ex.responseHeaders.add("Content-Type", "application/json")
        ex.sendResponseHeaders(code, data.size.toLong())
        ex.responseBody.use { it.write(data) }
    }

    /** A JSON body, or a 400 for a malformed one. */
    private fun json(ex: HttpExchange): JsonObject {
        val raw = ex.requestBody.use { it.readNBytes(100_001) }
        if (raw.size > 100_000) throw HttpError(413, mapOf("ok" to false, "error" to "body too large"))
        val text = String(raw, Charsets.UTF_8).ifBlank { "{}" }
        return runCatching { JsonParser.parseString(text).asJsonObject }
            .getOrElse { throw HttpError(400, mapOf("ok" to false, "error" to "expected JSON")) }
    }

    private fun query(ex: HttpExchange): Map<String, String> =
        (ex.requestURI.rawQuery ?: "").split('&').filter { it.isNotEmpty() }.associate {
            val k = it.substringBefore('=')
            val v = it.substringAfter('=', "")
            URLDecoder.decode(k, Charsets.UTF_8) to URLDecoder.decode(v, Charsets.UTF_8)
        }

    /**
     * Run on the EDT and wait for the answer. **Everything that reads or moves an editor or a
     * window goes through here**: the listener has threads of its own, and the platform answers
     * those questions only on the Event Dispatch Thread. `any` modality for read-only answers
     * (a Settings dialog open must not make `/ping` hang); the default for anything that opens
     * or moves, which then waits for the dialog — bounded, so the caller gets a 503 instead of
     * a socket held forever.
     */
    private fun <T> onEdt(modality: ModalityState = ModalityState.defaultModalityState(), block: () -> T): T {
        val f = CompletableFuture<T>()
        ApplicationManager.getApplication().invokeLater({
            try { f.complete(block()) } catch (e: Throwable) { f.completeExceptionally(e) }
        }, modality)
        return try {
            f.get(10, TimeUnit.SECONDS)
        } catch (_: TimeoutException) {
            throw HttpError(503, mapOf("ok" to false, "error" to "the IDE is busy (a modal dialog?)"))
        } catch (e: java.util.concurrent.ExecutionException) {
            throw e.cause ?: e
        }
    }

    private fun JsonObject.str(k: String): String? = get(k)?.takeIf { it.isJsonPrimitive }?.asString
    private fun JsonObject.raw(k: String): Any? = get(k)?.takeIf { it.isJsonPrimitive }?.asJsonPrimitive?.let {
        when { it.isNumber -> it.asDouble; it.isBoolean -> it.asBoolean; else -> it.asString }
    }
    private fun JsonObject.isFalse(k: String) = get(k)?.let { it.isJsonPrimitive && it.asJsonPrimitive.isBoolean && !it.asBoolean } == true

    // ------------------------------------------------------------------ projects

    /** The project whose frame was focused last — the one a reader is looking at. */
    private fun lastFocusedProject(): Project? =
        IdeFocusManager.getGlobalInstance().lastFocusedFrame?.project?.takeIf { !it.isDisposed && !it.isDefault }
            ?: Folders.openProjects().firstOrNull()

    private fun remember(project: Project) {
        lastTarget = WeakReference(project) to System.currentTimeMillis()
    }

    /** `ProjectUtil.focusProjectWindow(…, stealFocusIfAppInactive = true)` is the native raise
     *  the IDE's own "open from the command line" runs: on macOS it activates the application
     *  and brings that project's frame in front of the IDE's other frames. */
    private fun raise(project: Project) = ProjectUtil.focusProjectWindow(project, true)

    private fun firstFolder(project: Project?): String? = project?.let { Folders.ofProject(it).firstOrNull()?.name }

    // ------------------------------------------------------------------ routes

    private fun handle(ex: HttpExchange) {
        try {
            if (!Token.ok(token, ex.requestHeaders.getFirst("x-relay-token"))) {
                return send(ex, 403, mapOf("ok" to false, "error" to "bad token"))
            }
            val route = ex.requestMethod to ex.requestURI.path
            when (route) {
                "GET" to "/ping" -> send(ex, 200, ping())
                "GET" to "/editor-state" -> send(ex, 200, editorState())
                "POST" to "/command" -> command(ex)
                "POST" to "/open-file" -> openFile(ex)
                // M2/M3: the reviewed-version check across windows (review-open.js), the
                // before/after diff (diff.js), and the review page beside the code.
                "POST" to "/open-diff", "POST" to "/review-open", "POST" to "/open-url" ->
                    send(ex, 501, mapOf("ok" to false, "error" to "not yet in the IntelliJ plugin"))
                else -> send(ex, 404, mapOf("ok" to false))
            }
        } catch (e: HttpError) {
            runCatching { send(ex, e.code, e.body) }
        } catch (e: Throwable) {
            log.warn("human-review: request failed", e)
            runCatching { send(ex, 500, mapOf("ok" to false, "error" to (e.message ?: e.javaClass.simpleName))) }
        } finally {
            ex.close()
        }
    }

    // Who this IDE is, and which paths it owns. Callers route on `folders` — every folder of
    // every open project, each as its literal path and its realpath. `folder` is a *name*, kept
    // for older callers; a name is not an address.
    private fun ping(): Map<String, Any?> {
        val folders = Folders.dedupe(Folders.openProjects().flatMap { Folders.ofProject(it) })
        val (focused, folder, active) = onEdt(ModalityState.any()) {
            val p = lastFocusedProject()
            Triple(appFocused(), firstFolder(p),
                p?.let { FileEditorManager.getInstance(it).selectedTextEditor?.virtualFile?.path })
        }
        return linkedMapOf(
            "ok" to true,
            "app" to "idea",
            "bridge" to "human-review",
            "ide" to ApplicationNamesInfo.getInstance().fullProductName,
            "focused" to focused,
            "folder" to folder,
            "folders" to folders,
            "activeFile" to active,
        )
    }

    /** AWT's active window is null in every process that does not hold the keyboard. */
    private fun appFocused() = KeyboardFocusManager.getCurrentKeyboardFocusManager().activeWindow != null

    // What the focused project's editor is showing, for a caller checking that an open landed —
    // read-only. The file, the selection, and the range still highlighted with the rest muted
    // (RangeFocus.kt). `lastComment` is the PR comment-thread focus, which is M2.
    private fun editorState(): Map<String, Any?> = onEdt(ModalityState.any()) {
        val p = lastFocusedProject()
        val ed = p?.let { FileEditorManager.getInstance(it).selectedTextEditor }
        val selection = ed?.let {
            val sel = it.selectionModel
            fun pos(offset: Int) = it.offsetToLogicalPosition(offset)
                .let { lp -> linkedMapOf("line" to lp.line + 1, "character" to lp.column) }
            linkedMapOf("start" to pos(sel.selectionStart), "end" to pos(sel.selectionEnd))
        }
        linkedMapOf(
            "ok" to true,
            "folder" to firstFolder(p),
            "focused" to appFocused(),
            "activeFile" to ed?.virtualFile?.path,
            "selection" to selection,
            "lastComment" to null,
            "rangeFocus" to RangeFocus.active(),
        )
    }

    /** What `/command` will run. An allowlist, not any action id: the token gates the caller,
     *  the list gates what a caller can do. */
    private val COMMANDS = setOf(
        // Raise a project window. The page's editor badge asks the window that has the reviewed
        // checkout to come forward. With `&uri=`, the project owning it; without, the project
        // the bridge just acted on, else the last-focused one.
        "workbench.action.focusWindow",
        // The status-bar "human-review" click: serves this project's review when nothing does,
        // then opens the page.
        "humanReview.status",
    )

    /** What `/command` will run on a folder or file, named by `&uri=` — never without one. Kept
     *  apart from COMMANDS so a URI-taking command cannot be called bare (it would act on
     *  whatever happens to be selected), and so the URI is checked before anything runs: a
     *  `file:` URI inside one of the open projects' folders, nothing else. */
    private val URI_COMMANDS = setOf(
        // The Structure tab: a click on a package or a Maven module box shows that folder
        // selected in the owning project's Project view.
        "revealInExplorer",
    )

    private fun uriPath(raw: String?): String? = runCatching {
        val u = URI(raw ?: return null)
        if (u.scheme != "file") null else Path.of(u).toString()
    }.getOrNull()

    private fun command(ex: HttpExchange) {
        val q = query(ex)
        val id = q["id"] ?: ""
        val path = uriPath(q["uri"])
        val owner = path?.let { Folders.ownerProject(it) }
        if (id in URI_COMMANDS) {
            if (path == null || owner == null) {
                return send(ex, 400, mapOf("ok" to false, "error" to "$id needs a file: uri inside this IDE's project folders"))
            }
        } else if (id !in COMMANDS) {
            return send(ex, 400, mapOf("ok" to false, "error" to "not allowed: $id"))
        }
        val project: Project? = when (id) {
            "revealInExplorer" -> owner
            else -> owner ?: recentTarget() ?: onEdt(ModalityState.any()) { lastFocusedProject() }
        }
        project ?: return send(ex, 409, mapOf("ok" to false, "error" to "no project is open"))

        when (id) {
            "workbench.action.focusWindow" -> onEdt { raise(project) }
            "humanReview.status" -> ReviewStatus.of(project).click()
            "revealInExplorer" -> {
                val vf = LocalFileSystem.getInstance().refreshAndFindFileByNioFile(Path.of(path!!))
                    ?: return send(ex, 404, mapOf("ok" to false, "error" to "no such file or folder: $path"))
                onEdt {
                    ToolWindowManager.getInstance(project).getToolWindow(ToolWindowId.PROJECT_VIEW)
                        ?.activate { ProjectView.getInstance(project).select(null, vf, true) }
                    raise(project)
                }
                remember(project)
            }
        }
        send(ex, 200, mapOf("ok" to true, "folder" to firstFolder(project)))
    }

    private fun recentTarget(): Project? {
        val (ref, at) = lastTarget ?: return null
        return ref.get()?.takeIf { !it.isDisposed && System.currentTimeMillis() - at < 15_000 }
    }

    // Open a file at a line (or a range, `endLine`) in the project that owns it, and raise that
    // project's window. Opening a file focuses the editor *within* its frame but does not bring
    // the frame (or the IDE) to the front, so a click from a browser in front "did nothing" as
    // far as the reader could see; `raise()` is the native raise.
    private fun openFile(ex: HttpExchange) {
        val body = json(ex)
        val file = body.str("path") ?: ""
        if (!Path.of(file).isAbsolute) return send(ex, 400, mapOf("ok" to false, "error" to "absolute path required"))
        val line0 = maxOf(1, (RangeSpan.num(body.raw("line")) ?: 1.0).toInt()) - 1
        val endLine = body.raw("endLine")
        val warn = body.str("warn")?.takeIf { it.isNotEmpty() }
        val focus = !body.isFalse("focus")
        // `comment: true` (focus the PR comment thread on the line) is M2: accepted, ignored.

        // The owner by longest prefix; a file no project owns still opens, in the window the
        // reader was last in — the same as VS Code opening any absolute path it is handed.
        val project = Folders.ownerProject(file) ?: onEdt(ModalityState.any()) { lastFocusedProject() }
            ?: return send(ex, 404, mapOf("ok" to false, "error" to "no project is open", "path" to file))
        // Off the EDT: a refresh that finds a file created outside the IDE must not run inside
        // a write-intent EDT event.
        val vf = LocalFileSystem.getInstance().refreshAndFindFileByNioFile(Path.of(file))
        if (vf == null || vf.isDirectory) {
            return send(ex, 404, mapOf("ok" to false, "error" to "cannot open $file", "path" to file))
        }

        val result = onEdt {
            val editor = FileEditorManager.getInstance(project)
                .openTextEditor(OpenFileDescriptor(project, vf, line0, 0), true) ?: return@onEdt null
            // A caller that found the file edited since the commit it is quoting says so, on the
            // line the reader lands on rather than in a toast elsewhere.
            if (warn != null) EditedMark.mark(editor, line0, warn) else EditedMark.clear()
            val ranged = RangeFocus.focus(project, editor, line0 + 1, endLine)
            if (focus) runCatching { raise(project) }  // the file is open, which is the part that matters
            ranged
        } ?: return send(ex, 404, mapOf("ok" to false, "error" to "cannot open $file in an editor", "path" to file))
        remember(project)

        val out = linkedMapOf<String, Any?>("ok" to true, "path" to vf.path, "line" to line0 + 1)
        if (result) out["endLine"] = RangeSpan.num(endLine)?.toInt()
        send(ex, 200, out)
    }
}

/** Starts the bridge when the first project opens; later projects find it running. */
class HumanReviewStartup : ProjectActivity {
    override suspend fun execute(project: Project) {
        service<HumanReviewBridge>().start()
    }
}
