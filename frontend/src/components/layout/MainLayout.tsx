/**
 * 主布局组件
 */
import React from 'react'
import { Layout } from 'antd'
import styles from './MainLayout.module.css'

const { Header, Content, Footer } = Layout

interface MainLayoutProps {
  children: React.ReactNode
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  return (
    <Layout className={styles.layout}>
      <Header className={styles.header}>
        <h1 className={styles.title}>AI视频创作智能体</h1>
      </Header>
      <Content className={styles.content}>{children}</Content>
      <Footer className={styles.footer}>
        AI视频创作智能体 ©2024 - 基于 LangGraph
      </Footer>
    </Layout>
  )
}
