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
            muted. A <b>human-review</b> status-bar item says whether this checkout's review is
            being served, and serves it on a click.
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

    runIde {
        // A sandbox IDE asks "Trust this project?" in a modal, which blocks the EDT — and every
        // bridge route that runs on the EDT with it, so a curl against a fresh sandbox hangs.
        jvmArgs("-Didea.trust.all.projects=true")
    }
}
