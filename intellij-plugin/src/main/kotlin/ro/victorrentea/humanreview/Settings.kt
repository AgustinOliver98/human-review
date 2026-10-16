package ro.victorrentea.humanreview

import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.components.service
import com.intellij.openapi.options.Configurable
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.FormBuilder
import javax.swing.JComponent

/** `serveScript` — absolute path to `serve-review.py`, for the status-bar item to start a server
 *  with. Empty: the copy installed with the `human-review` Claude Code plugin, else
 *  `~/workspace/human-review`. The twin of VS Code's `humanReview.serveScript`. */
@Service(Service.Level.APP)
@State(name = "HumanReviewSettings", storages = [Storage("human-review.xml")])
class HumanReviewSettings : PersistentStateComponent<HumanReviewSettings.Data> {
    class Data {
        var serveScript: String = ""
    }

    private var data = Data()

    override fun getState(): Data = data
    override fun loadState(state: Data) {
        data = state
    }

    var serveScript: String
        get() = data.serveScript
        set(v) { data.serveScript = v.trim() }

    companion object {
        fun get(): HumanReviewSettings = service()
    }
}

/** Settings → Tools → Human Review. */
class HumanReviewConfigurable : Configurable {
    private var field: JBTextField? = null

    override fun getDisplayName() = "Human Review"

    override fun createComponent(): JComponent {
        val f = JBTextField(HumanReviewSettings.get().serveScript).also { field = it }
        f.emptyText.text = "found automatically: the Claude Code plugin's copy, else ~/workspace/human-review"
        return FormBuilder.createFormBuilder()
            .addLabeledComponent("serve-review.py:", f)
            .addComponentFillVertically(javax.swing.JPanel(), 0)
            .panel
    }

    override fun isModified() = field?.text?.trim() != HumanReviewSettings.get().serveScript

    override fun apply() {
        HumanReviewSettings.get().serveScript = field?.text ?: ""
    }

    override fun reset() {
        field?.text = HumanReviewSettings.get().serveScript
    }

    override fun disposeUIResources() {
        field = null
    }
}
