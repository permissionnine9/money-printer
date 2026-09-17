/**
 * 主应用组件（路由入口）
 */
import { Routes, Route } from 'react-router-dom'
import { MainLayout } from './components/layout/MainLayout'
import WorkflowPage from './pages/WorkflowPage'
import ModelsPage from './pages/ModelsPage'
import PromptsPage from './pages/PromptsPage'

import './App.css'

function App() {
  return (
    <MainLayout>
      <Routes>
        <Route path="/" element={<WorkflowPage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/prompts" element={<PromptsPage />} />
      </Routes>
    </MainLayout>
  )
}

export default App
