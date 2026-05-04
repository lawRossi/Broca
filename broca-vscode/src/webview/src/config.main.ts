import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ConfigApp from './ConfigApp.vue'
import { applyVSCodeTheme } from './utils/theme'

applyVSCodeTheme()

const app = createApp(ConfigApp)
app.use(createPinia())
app.mount('#app')
