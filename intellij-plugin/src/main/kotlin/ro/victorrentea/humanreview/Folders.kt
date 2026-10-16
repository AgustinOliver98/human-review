package ro.victorrentea.humanreview

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.ProjectManager
import com.intellij.openapi.roots.ProjectRootManager
import com.intellij.openapi.util.Computable
import java.io.File
import java.nio.file.Path

// Which paths a project window owns, and which window owns a path.
//
// The caller (serve-review.py) routes on `folders` from `/ping`, longest prefix first, the same
// way for VS Code and for IntelliJ. A VS Code window owns its workspace folders; an IntelliJ
// project owns its base directory *and* every content root — a Maven/Gradle import or an
// "attached" directory can put a root outside the base path. One IDE process answers for all
// its project windows at once, so `/ping` lists the folders of every open project, and the
// bridge itself picks the project inside the process with the same longest-prefix rule.

/** A folder as `/ping` reports it: a name for humans, the literal path, and its realpath (a
 *  checkout reached through a symlink is one tree under two names). */
data class Folder(val name: String, val path: String, val realPath: String)

object Folders {
    private val SEP = File.separator

    fun inside(p: String, dir: String): Boolean =
        dir.isNotEmpty() && (p == dir || p.startsWith(if (dir.endsWith(SEP)) dir else dir + SEP))

    fun of(path: String): Folder {
        val p = Path.of(path)
        val real = runCatching { p.toRealPath().toString() }.getOrDefault(p.toString())  // the folder went away under us
        return Folder(p.fileName?.toString() ?: p.toString(), p.toString(), real)
    }

    /** Folders listed once each: two projects can share a content root, and a base path is often
     *  also a content root. */
    fun dedupe(folders: List<Folder>): List<Folder> = folders.distinctBy { it.path }

    /**
     * The key whose folder contains `file` deepest, or null. Both spellings of the file (as
     * given, and its realpath) against both spellings of every folder: a window opened through a
     * symlink and a caller holding the real path are still the same tree.
     */
    fun <T> owner(file: String, fileReal: String?, entries: List<Pair<T, Folder>>): T? {
        var best: T? = null
        var bestLen = -1
        for ((key, f) in entries) {
            for (dir in listOf(f.path, f.realPath)) {
                for (p in listOfNotNull(file, fileReal)) {
                    if (inside(p, dir) && dir.length > bestLen) {
                        best = key
                        bestLen = dir.length
                    }
                }
            }
        }
        return best
    }

    // ------------------------------------------------------------------ the IDE half

    fun openProjects(): List<Project> =
        ProjectManager.getInstance().openProjects.filter { !it.isDisposed && !it.isDefault }

    /** The base path first, then every local content root. */
    fun ofProject(project: Project): List<Folder> {
        val paths = LinkedHashSet<String>()
        project.basePath?.let { paths += it }
        // Application.runReadAction, not ReadAction.compute: deprecated from 2026.1 for a
        // replacement (computeBlocking) that 2024.3 does not have.
        val roots = ApplicationManager.getApplication().runReadAction(Computable {
            if (project.isDisposed) emptyArray() else ProjectRootManager.getInstance(project).contentRoots
        })
        roots.filter { it.isInLocalFileSystem }.forEach { paths += it.path }
        return paths.map(::of)
    }

    /** Which open project owns `file`, longest prefix across every project's folders. */
    fun ownerProject(file: String): Project? {
        val real = runCatching { Path.of(file).toRealPath().toString() }.getOrNull()
        val entries = openProjects().flatMap { p -> ofProject(p).map { p to it } }
        return owner(file, real, entries)
    }
}
