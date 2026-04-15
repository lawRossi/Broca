import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import router from './router'
import { createPinia } from 'pinia'
import App from './App.vue'

// 确保我们的样式在 Element Plus 之后加载
import './styles/index.css'

const app = createApp(App)
app.use(createPinia()).use(router).use(ElementPlus).mount('#app')
