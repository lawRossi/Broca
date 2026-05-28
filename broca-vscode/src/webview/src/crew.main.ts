import { createApp } from 'vue'
import { createPinia } from 'pinia'
import CrewApp from './CrewApp.vue'
import { applyVSCodeTheme } from './utils/theme'

applyVSCodeTheme()

const app = createApp(CrewApp)
app.use(createPinia())
app.mount('#app')
