"""
cli.core — CLI 基础设施包

职责：
  - 提供命令注册（registry）、执行（runner）、配置（config）、协议（protocol）等通用能力
  - 所有平台适配器共享本包，但平台适配器之间禁止互相 import

设计原则：
  - 纯工具层，无业务状态
  - 进程级配置单例，线程安全
"""
