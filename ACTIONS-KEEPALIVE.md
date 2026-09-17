# Codex 保活：GitHub Actions 版

基于上游 AlliotTech/codex-queue-bot 的 codex-healthcheck.sh，只执行一次原生 Codex 调用，不启动 Web、SQLite 或机器人常驻服务，也不调用 Claude。

## 不耗额度的测试

Actions → Codex Keepalive → Run workflow → mode=smoke。

安装固定版本 Codex CLI，检查失败/空响应退出码，并让真实 Codex CLI 请求 runner 内 127.0.0.1 上的模拟 Responses 服务。smoke 成功不代表真实 AnyRouter 接口可用。

## 配置真实接口

Settings → Secrets and variables → Actions：

| 类型 | 名称 | 内容 |
|---|---|---|
| Secret | ANYROUTER_API_KEY | AnyRouter Codex API Key；不要提交进仓库 |
| Variable | ANYROUTER_BASE_URL | 控制台提供的 Codex API base URL，须支持 Responses；不要照搬 Claude 地址 |
| Variable | CODEX_MODEL | 该接口当前支持的 Codex 模型 ID |
| Variable | KEEPALIVE_ENABLED | 定时开关；默认 false，真实单次测试成功后再设 true |

API Key 只注入实际调用步骤，不提供给依赖安装、代码检出或 smoke job。运行使用独立临时 HOME/CODEX_HOME，不复制个人 Codex 登录信息。

## 真实单次试跑

Actions → Codex Keepalive → Run workflow → mode=live。

配置缺失时明确失败并列出字段，不发送 API 请求。只有 Codex 退出 0 且最终响应非空，才记为 LIVE PASS。真实调用消耗服务额度；本项目不保证排队优先级改善。

## 定时与停止

KEEPALIVE_ENABLED=true 后，每小时第 17 分钟运行一次（cron 为 17 * * * *，北京时间同样每小时第 17 分钟）。每次调用一次后退出；GitHub 定时触发可能延迟。

设为 false 或在 Actions 页面禁用 Codex Keepalive，即可停止。默认尚未开启，避免配置未完成时发起定时请求。

原 anyrouter-check-in 仓库的北京时间每天 08:00 签到任务不受影响。

## 本 Fork 的修改

- 新增 Actions 单次入口、配置校验、无真实额度消耗的 smoke 测试。
- 修复原脚本 --once 吞掉失败退出码、空响应仍返回 0 的问题。
- 禁止 Codex 启动的 shell 子进程继承 provider 密钥环境变量。
- 已停用与保活无关的容器镜像发布工作流。
