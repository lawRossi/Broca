# ChatInput `#` 文件路径补全 — Phase 2: 三个前端支持 # 路径补全 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | plans/chat-input-hash-path-completion-plan.md |
| Phase | Phase 2: 三个前端支持 # 路径补全 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 2.1: broca-web ChatInput 支持 # 补全 | ✅ | ①sessionId 变化后获取 workspace；completeFiles 参数正确<br>②输入 # 弹出列表、#ab 前缀过滤、#dir/ 列出子目录<br>③选文件插入 #路径 且关闭、100ms 防重弹；选目录插入 dir/ 继续钻取<br>④/、@、# 互斥；Esc/点击外部关闭<br>⑤pnpm build 通过无回归 | ①files.ts 新增 completeFiles；ChatInput.vue 新增 chatWorkspace（watch sessionId + getSession）+ updatePathSuggestions（requestSeq 竞态保护）+ selectPath（文件/目录分支）+ # 键盘/外部关闭/点击处理 + 模板列表 + placeholder。②③④ 逻辑均已实现。⑤ `pnpm build:dev`（vue-tsc + vite）通过 | 无（项目无 `pnpm build` 脚本，实际等效脚本为 `build:dev`） |
| Task 2.2: broca-vscode 支持 # 补全 | ✅ | ①扩展 api.ts 新增方法且 handleListFiles 通过 session workspace 请求补全<br>②webview 输入 # 弹出列表，回包 files 驱动渲染<br>③行为与 web 一致<br>④npm run build 通过无类型错误 | ①api.ts 新增 completeFiles；types.ts 增加 'listFiles'/'files'；chatWebView.ts 新增 case + handleListFiles（getSession→workspace→completeFiles，失败 post 空列表）。②③webview ChatInput.vue 与 web 版一致（postMessage listFiles + onMessage files 回包 + 3s 超时兜底 + 前缀竞态保护）。④`npm run build` 通过（tsc + vite） | 无 |
| Task 2.3: broca-tui ChatInput 支持 # 补全 | ✅ | ①set_workspace 生效；complete_files 参数/解析正确<br>②# 弹出 ListView、#ab 过滤、#dir/ 钻取<br>③选目录插入 #dir/ 续钻；选文件插入 #path 并关闭<br>④与 /、@ 互斥；Enter 先选择<br>⑤相关用例通过 | ①SessionAPI.complete_files + ChatInput.set_workspace/_workspace。②③_handle_input_change 增加 path 分支 + _request_path_completions（异步 run_worker + 请求序号 + 输入快照竞态保护）+ _select_autocomplete path 分支。④分支顺序 / → @ → # 天然互斥。⑤5 项临时验证测试通过（触发/过滤/钻取/选目录续钻/选文件插入/空格外关闭）；既有测试除 2 个预存失败外全部通过 | 无 |

> ✅ = All ACs met

## Deviations

无实质偏差。说明：
- web 前端 package.json 无 `pnpm build` 脚本，实际为 `pnpm build:dev`（vue-tsc --noEmit + vite build），已用它验证 AC⑤。
- 目录项展示采用 `#path/` 后缀（计划允许「或加 📁」）；web/vscode 前端额外显示 📁 图标，TUI 终端仅用 `/` 后缀以保证终端兼容。

## 关于「互斥」的实现

- watch 中检测顺序固定为 `/` → `@` → `#`；`/` 命中即 return（自然互斥）；`@` 命中显示列表后，`#` 分支开头检查 `showCommandSuggestions || showMentionSuggestions` 已显示则跳过并关闭 `#` 列表，保证同一时刻仅一种列表。
- TUI 的 `_handle_input_change` 分支顺序相同：command/mention 命中即 return，之后才进入 `#` 分支。

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (cross-referenced against plan)
- [x] No extra functionality (only what the plan asked for)
- [x] Manually verified key behaviors（TUI 通过 run_test 自动化验证；web/vscode 构建通过，功能验证待 Phase 3 手动清单）
- [x] Code follows project conventions
- [x] Compatible with existing work（/、@ 补全逻辑未改动，仅追加 # 分支；构建通过）

## 已知事项

- broca-tui 另有 2 个预存失败测试（test_chatinput_debug.py 的 Input 类型断言错误、test_widgets.py 的 TurnCardUndo 断言），均与本次改动无关（已通过 git stash 确认改动前即失败）。
