/**
 * 主应用组件（路由入口）
 */
import { Routes, Route } from 'react-router-dom'
import { MainLayout } from './components/layout/MainLayout'
import WorkflowPage from './pages/WorkflowPage'
import ScriptWorkflowPage from './pages/ScriptWorkflowPage'
import ModelsPage from './pages/ModelsPage'
import PromptsPage from './pages/PromptsPage'
import MaterialsPage from './pages/MaterialsPage'
import AgentConcurrencyPage from './pages/AgentConcurrencyPage'

import './App.css'

function App() {
  return (
    <MainLayout>
      <Routes>
        <Route path="/script" element={<ScriptWorkflowPage />} />
        <Route path="/" element={<WorkflowPage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/prompts" element={<PromptsPage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/settings/agent-concurrency" element={<AgentConcurrencyPage />} />
      </Routes>
    </MainLayout>
  )
}

export default App
