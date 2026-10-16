import org.jetbrains.intellij.platform.gradle.TestFrameworkType
import org.jetbrains.intellij.platform.gradle.tasks.VerifyPluginTask.FailureLevel
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

// Trimmed from ~/workspace/live-coding: same Gradle, Kotlin and IntelliJ Platform Gradle
// Plugin versions (they are known to build together on this machine), without the changelog,
// signing, Marketplace publishing and bundled-plugin dependencies this plugin does not need.

fun properties(key: String) = providers.gradleProperty(key)

plugins {
    id("java")
    id("org.jetbrains.kotlin.jvm") version "2.1.0"
    id("org.jetbrains.intellij.platform") version "2.16.0"
}

group = properties("pluginGroup").get()
version = properties("pluginVersion").get()

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        intellijIdeaCommunity(properties("platformVersion").get())
        testFramework(TestFrameworkType.Platform)
    }
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.opentest4j:opentest4j:1.3.0")
}

intellijPlatform {
    pluginConfiguration {
        id = "ro.victorrentea.human-review"
        name = "Human Review"
        version = properties("pluginVersion")
        vendor {
            name = "Victor Rentea"
            url = "https://github.com/victorrentea/human-review"
        }
        description = """
            The IntelliJ end of a <a href="https://github.com/victorrentea/human-review">/human-review</a>
            page: every <code>File.java:49-51</code> reference in the review opens in the project
            window that has the reviewed checkout, as a highlighted range with the rest of the file
            muted — or, for a fix, as a before/after diff. A reference opens only where the file is
            the version that was reviewed, and says so plainly when no window has it. A
            <b>human-review</b> status-bar item says whether this checkout's review is being
            served, and serves it on a click.
        """.trimIndent()
        changeNotes = """
            <h3>0.2.0</h3>
            <ul>
              <li><b>Before/after diffs</b>: a fix on the review page opens as a diff — the file at
                  the base commit on the left, read-only; the working tree on the right, editable —
                  scrolled to the line the fix is about.</li>
              <li><b>The reviewed version, or a plain refusal</b>: a reference opens only in a
                  window whose checkout has the file exactly as it was reviewed (here, or in
                  another IntelliJ or VS Code window); otherwise it says so, with a prompt to copy
                  for a coding agent. A file edited since is marked on the line you land on.</li>
              <li><b>Pages read off disk</b>: <code>jetbrains://idea/human-review/…</code> links
                  (open, diff, review-open) reach the plugin with no review server running
                  (needs JetBrains Toolbox, which owns the <code>jetbrains://</code> scheme).</li>
              <li>A plugin icon.</li>
            </ul>
            <h3>0.1.0</h3>
            <ul>
              <li>References open in the project window that owns the file, as a highlighted range.</li>
              <li>A <b>human-review</b> status-bar item: is this checkout's review served?</li>
            </ul>
        """.trimIndent()
        ideaVersion {
            sinceBuild = properties("pluginSinceBuild")
            untilBuild = provider { null }
        }
    }

    pluginVerification {
        failureLevel = listOf(
            FailureLevel.COMPATIBILITY_PROBLEMS,
            FailureLevel.INVALID_PLUGIN,
            FailureLevel.MISSING_DEPENDENCIES,
        )
        ides {
            // The IDE runIde/buildPlugin already use: nothing else to download.
            create(properties("platformType").get(), properties("platformVersion").get())
        }
    }
}

kotlin {
    jvmToolchain(21)
    compilerOptions {
        jvmTarget = JvmTarget.JVM_21
    }
}

java {
    sourceCompatibility = JavaVersion.VERSION_21
    targetCompatibility = JavaVersion.VERSION_21
}

tasks {
    wrapper {
        gradleVersion = properties("gradleVersion").get()
    }

    test {
        // Never the real ~/.human-review/ide/: a bridge a test starts must not be routed to, and
        // a hand-over a test makes must not reach an editor someone is working in.
        systemProperty("human-review.registry.dir", layout.buildDirectory.dir("test-registry").get().asFile.path)
        systemProperty("java.awt.headless", "true")
    }

    runIde {
        // A sandbox IDE asks "Trust this project?" in a modal, which blocks the EDT — and every
        // bridge route that runs on the EDT with it, so a curl against a fresh sandbox hangs.
        jvmArgs("-Didea.trust.all.projects=true")
    }
}
