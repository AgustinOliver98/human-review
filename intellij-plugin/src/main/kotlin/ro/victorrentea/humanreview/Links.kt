package ro.victorrentea.humanreview

import com.intellij.notification.NotificationAction
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.application.JBProtocolCommand
import com.intellij.openapi.application.JBProtocolCommandResult
import com.intellij.openapi.application.ModalityState
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.ide.CopyPasteManager
import com.intellij.openapi.project.Project
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.awt.datatransfer.StringSelection
import java.io.File
import java.nio.file.Path

// `jetbrains://idea/human-review/…` — the channel a page has when it has no server. The port of
// vscode-extension/uri-handler.js.
//
// The Human Review guide read over http can ask its own origin to do things (that is
// `/__open__` and `/__open_diff__`). Read straight off disk from a browser — which is how it is
// actually read — a `file://` page has no origin worth asking and no way to reach loopback, so
// every reference degrades to the one thing a browser can still do: hand a URL to the OS. An
// `idea://open?file=…` opens the file; it cannot open a *diff*, because a diff needs the
// before-side materialised out of git first, and no page can do that for itself. A
// `jetbrains://` protocol command can: the IDE routes `jetbrains://idea/<command>/<target>?…` to
// the plugin that registered `<command>`.
//
// macOS hands `jetbrains://` to JetBrains Toolbox, which passes it to the IntelliJ it manages;
// the IDE itself registers only `idea://`. Without Toolbox the link has no taker, which is why
// the page sends it only to a reader who picked IntelliJ (the masthead's IDE choice).
//
// **The window the IDE picks is not the window that owns the file.** So the handler does not
// assume it: it finds the project that owns the path (longest prefix wins) among this IDE's
// windows and every other registered bridge, and hands the work over when that is not here.

/** What a link asks for, parsed and nothing else — the part a test can hold. */
sealed interface LinkRequest {
    data class Open(val file: String, val line: Int, val endLine: String?) : LinkRequest
    data class Diff(val file: String, val base: String, val line: Int) : LinkRequest
    data class ReviewOpen(val ref: ReviewRef) : LinkRequest
    data class Unknown(val target: String) : LinkRequest
}

object Links {
    const val COMMAND = "human-review"

    private fun line(v: String?) = maxOf(1, RangeSpan.num(v)?.takeIf { !it.isNaN() }?.toInt() ?: 1)

    /** `target` is the path segment after the command (`open`, `diff`, `review-open`); the
     *  parameters arrive percent-decoded, a path with spaces in it included. */
    fun parse(target: String?, q: Map<String, String>): LinkRequest = when (target?.trim('/')) {
        "open" -> LinkRequest.Open(q["file"] ?: "", line(q["line"]), q["endLine"]?.ifEmpty { null })
        "diff" -> LinkRequest.Diff(q["file"] ?: "", q["base"] ?: "", line(q["line"]))
        "review-open" -> LinkRequest.ReviewOpen(ReviewRef(
            file = q["file"] ?: "", line = q["line"], endLine = q["endLine"]?.ifEmpty { null },
            sha = q["sha"] ?: "", root = q["root"] ?: "", branch = q["branch"] ?: ""))
        else -> LinkRequest.Unknown(target ?: "")
    }

    /** Who owns `file`: a key from `here` (this IDE's projects) or `there` (other bridges),
     *  longest prefix over both spellings. Here first, so an equal claim stays in this IDE. */
    fun <K> owner(file: String, here: List<Pair<K, Folder>>, there: List<Pair<K, Folder>>): K? {
        val real = runCatching { Path.of(file).toRealPath().toString() }.getOrNull()
        return Folders.owner(file, real, here + there)
    }

    // ------------------------------------------------------------------ the IDE half

    private val log = thisLogger()

    fun handle(req: LinkRequest, registry: Path = Registry.DIR) {
        when (req) {
            is LinkRequest.Open -> openPlainRouted(req.file, req.line, req.endLine, registry)
            is LinkRequest.Diff -> diff(req, registry)
            is LinkRequest.ReviewOpen -> reviewOpen(req.ref, registry)
            is LinkRequest.Unknown -> warn("Human Review: nothing handles /${req.target}")
        }
    }

    private sealed interface Owner {
        data class Here(val project: Project) : Owner
        data class There(val peer: LivePeer) : Owner
    }

    /** Staleness as everywhere else: a peer is trusted only once it answers its own `/ping`. */
    private fun ownerOf(file: String, registry: Path): Owner? = owner(
        file,
        Folders.openProjects().flatMap { p -> Folders.ofProject(p).map { Owner.Here(p) as Owner to it } },
        Peers.live(registry).flatMap { lp -> lp.folders.map { Owner.There(lp) as Owner to it } },
    )

    private fun diff(req: LinkRequest.Diff, registry: Path) {
        val (file, base, line) = req
        // Validated here as well as in DiffOpen, so a bad ref never reaches the network hop
        // either. Cheap, and the two callers of the diff are not the only future ones.
        if (!DiffOpen.usableRef(base)) {
            warn("Human Review: ${if (base.isNotEmpty()) "that is not a git ref" else "no git ref given"} — opening the file instead.")
            return openPlainRouted(file, line, null, registry)
        }
        if (!File(file).isAbsolute) return

        val owner = ownerOf(file, registry)
        if (owner is Owner.There) {
            val res = Peers.call(owner.peer.peer, "POST", "/open-diff", mapOf("file" to file, "base" to base, "line" to line))
            if (res?.second?.get("ok")?.let { it.isJsonPrimitive && it.asBoolean } == true) return
            // The owning window refused (no such ref there, file unchanged, or it went away
            // between the ping and now). Say why, once, and still put the reader in the file —
            // never a silent no-op, which is the failure that made this look broken.
            val why = res?.second?.get("error")?.takeIf { it.isJsonPrimitive }?.asString
                ?: "the window that owns it did not answer"
            warn("Human Review: no diff ($why) — opening the file instead.")
            return openPlainRouted(file, line, null, registry)
        }

        // Either a project here owns it, or nobody does. Doing it here is then the best
        // available answer; the diff still refuses a path outside every project, and the
        // fallback below catches that.
        val refused = runCatching { DiffOpen.open(file, base, line, true) }.getOrElse { it.message ?: "$it" }
        if (refused != null) {
            warn("Human Review: no diff ($refused) — opening the file instead.")
            openPlainRouted(file, line, null, registry)
        }
    }

    /**
     * The plain-file fallback, routed the same way the diff is.
     *
     * Falling back must not quietly undo the routing: opening the file in whichever window the
     * IDE happened to pick is the original bug wearing a different hat — the right file, in a
     * window belonging to another checkout. So the owner is resolved first here too, and only a
     * path nobody owns is opened in the window the reader was last in.
     */
    fun openPlainRouted(file: String, line: Int, endLine: String?, registry: Path = Registry.DIR) {
        if (file.isEmpty() || !File(file).isAbsolute) return
        val owner = ownerOf(file, registry)
        if (owner is Owner.There) {
            val res = Peers.call(owner.peer.peer, "POST", "/open-file",
                mapOf("path" to file, "line" to line, "endLine" to endLine, "focus" to true))
            if (res?.second?.get("ok")?.let { it.isJsonPrimitive && it.asBoolean } == true) return
        }
        val project = (owner as? Owner.Here)?.project ?: Ide.onEdt(ModalityState.any()) { Ide.lastFocusedProject() } ?: return
        val vf = Ide.findFile(file) ?: return  // the file moved; a warning above already said something
        runCatching { Ide.open(project, vf, line, endLine, null, true) }
    }

    /** A guide read off disk has nowhere to show "no window has this", so it is said here, in
     *  the IDE the link was handed to — with the prompt one click away. */
    private fun reviewOpen(ref: ReviewRef, registry: Path) {
        val (status, done) = ReviewOpen.open(ref, registry)
        if (status == 200) return
        // A guide built before it carried its commit cannot be checked; it opens as it always did.
        if (done["error"] == "bad-request") return openPlainRouted(ref.file, line(ref.line as String?), ref.endLine as String?, registry)
        val message = done["message"] as? String ?: "could not open ${File(ref.file).name}"
        val prompt = done["prompt"] as? String ?: return warn("Human Review: $message")
        notify(message, NotificationType.ERROR, prompt)
    }

    private fun warn(text: String) = notify(text, NotificationType.WARNING, null)

    private fun notify(text: String, type: NotificationType, prompt: String?) {
        log.info("human-review link: $text")
        val project = runCatching { Ide.onEdt(ModalityState.any()) { Ide.lastFocusedProject() } }.getOrNull()
        val n = NotificationGroupManager.getInstance().getNotificationGroup("Human Review").createNotification(text, type)
        if (prompt != null) {
            n.addAction(NotificationAction.createSimpleExpiring("Copy prompt") {
                CopyPasteManager.getInstance().setContents(StringSelection(prompt))
            })
        }
        n.notify(project)
    }
}

/** `jetbrains://idea/human-review/<open|diff|review-open>?…`, registered as `jbProtocolCommand`. */
class HumanReviewProtocolCommand : JBProtocolCommand(Links.COMMAND) {
    // The work raises the project window that owns the file. The IDE's own "focus the IDE
    // window" after a command would then bring forward whichever frame it considers current —
    // possibly another checkout's, in front of the one just raised — so it is declined here.
    override suspend fun executeAndGetResult(target: String?, parameters: Map<String, String>, fragment: String?): JBProtocolCommandResult {
        withContext(Dispatchers.IO) { Links.handle(Links.parse(target, parameters)) }
        return JBProtocolCommandResult(null, false)
    }
}
