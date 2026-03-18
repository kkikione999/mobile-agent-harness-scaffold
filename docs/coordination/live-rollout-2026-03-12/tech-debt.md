# Live Rollout Tech Debt - 2026-03-12

记录格式：

- 时间
- 任务编号
- 问题
- 影响
- 复现命令
- 建议下一步

## Open Items

- `TD-002`
  - 问题：`/Users/josh_folder/harmony/app` 的 `develop` 与 `develop-whc` 已明显分叉，直接 `merge --no-ff develop` 会把大量无关历史一并带入。
  - 影响：子 slice 即使只改 2 个文件，也可能在本地 merge 阶段引入数百个无关文件变更，污染滚动合并边界。
  - 复现：`git -C /Users/josh_folder/harmony/app checkout develop-whc && git -C /Users/josh_folder/harmony/app merge --no-ff develop`
  - 下一步：后续 Harmony app slice 应优先 `cherry-pick` 目标 commit，而不是直接 merge 整个 `develop`。

- `TD-004`
  - 时间：2026-03-12
  - 任务：Task 04
  - 问题：文本专项 live flow 仍失败。`flow_text.json` 显示 stable open/bridge 已通过，但 `search.query_input` 这条文本值校验仍未成为稳定通过项。
  - 影响：当前“按具体文本值校验搜索输入框”仍不能作为稳定通过项。
  - 复现：`ANDROID_SERIAL=emulator-5554 python3 /Users/josh_folder/scaffold/tools/live_android_verify.py --app com.utell.youtiao --serial emulator-5554 --press-element todo_calendar.search_bar --fill-element search.query_input --verify-element search.query_input --fill-text livecheck123 --verify-expected livecheck123`
  - 下一步：交给 app bridge freshness / search semantics 任务继续收口。

- `TD-005`
  - 时间：2026-03-12
  - 任务：Task 01 Retry
  - 问题：首次重派 Task 01 时，子 agent 运行环境返回 `503 Service Unavailable`，属于外部执行通道故障，不是任务结论。
  - 影响：`task-01-app-bridge-screen-freshness.md` 还没有有效执行结果，当前 bridge freshness 仍缺 app-side 修复回流。
  - 复现：子 agent 请求返回 `503 Service Unavailable`，request id `c878a335-63b0-429a-8944-acdb23b3ecd1`
  - 下一步：重派 Task 01；若再次失败，改用新的 agent 槽位串行执行，不阻塞其余 slice。

- `TD-006`
  - 时间：2026-03-12
  - 任务：Task 02
  - 问题：Task 02 已在 `/Users/josh_folder/harmony/app` 产出本地 commit `8af2ef7e fix(search): expose live query semantics`，但随后直接把 `develop` merge 进 `develop-whc`，污染了 slice 边界。
  - 影响：Task 02 的有效业务改动本来很小，但当前 `develop-whc` 已 ahead 69，不能直接把这次 merge 当成干净可回滚 slice。
  - 复现：`git -C /Users/josh_folder/harmony/app branch -vv`
  - 下一步：后续只接受 `cherry-pick 8af2ef7e` 或等价最小变更，不再 merge 整个 `develop`。

- `TD-007`
  - 时间：2026-03-12
  - 任务：Task 03 Retry
  - 问题：Task 03 在重派后仍遇到外部 provider `503 Service Unavailable`，目前没有有效实现结果回流。
  - 影响：harness live flow stabilization 暂时只能依赖当前工作树已有改动，缺少独立 slice 验证与整理。
  - 复现：`/Users/josh_folder/scaffold/docs/coordination/live-rollout-2026-03-12/agent-logs/T3.log`
  - 下一步：继续重派；provider 恢复前不阻塞其他 slice。

- `TD-008`
  - 时间：2026-03-12
  - 任务：Task 05 Retry
  - 问题：Task 05 在重派后仍遇到外部 provider `503 Service Unavailable`，无法依赖专门 agent 做持续的 debt/merge queue 维护。
  - 影响：当前 `tech-debt.md` 和 `merge-queue.md` 需要由协调器临时兜底维护。
  - 复现：`/Users/josh_folder/scaffold/docs/coordination/live-rollout-2026-03-12/agent-logs/T5.log`
  - 下一步：provider 恢复后继续重派；恢复前由协调器继续维护队列。

- `TD-009`
  - 时间：2026-03-13
  - 任务：Task 01
  - 问题：额外信号测试 `flutter test --no-pub test/features/search/presentation/pages/search_page_test.dart` 失败，原因不是 Task 01 改动本身，而是仓库当前缺失 `lib/features/todo_calendar/...` 下若干生成的 `freezed` part 文件。
  - 影响：Harmony app 的部分 focused Flutter test 无法作为稳定回归信号，影响后续 slice 的额外验证质量。
  - 复现：`cd /Users/josh_folder/harmony/app && flutter test --no-pub test/features/search/presentation/pages/search_page_test.dart`
  - 状态更新（2026-03-13 / Task 09）：已通过定向 `build_runner` 恢复 `todo_calendar_page/state.freezed.dart`、`todo_task_block/state.freezed.dart`、`todo_section_header/state.freezed.dart`，原始 `todo_calendar` 缺件已消除。
  - 状态更新（2026-03-13 / Task 12）：已在 `/Users/josh_folder/worktrees/harmony-task12-codegen/app` 移除 repo root 与 app root 的 `*.g.dart` / `*.freezed.dart` ignore，并执行 `dart run build_runner build --delete-conflicting-outputs`；本次恢复了 `39` 个缺失生成文件。
  - 当前状态：阻塞已解除。`flutter test test/features/search/presentation/pages/search_page_test.dart` 现已通过，不能再把该链路的剩余问题归因到 codegen 缺件。
  - 下一步：如后续 search / route 聚焦验证仍失败，直接按真实业务逻辑或测试断言继续定位，不再回退到“缺少生成文件”的归因。

- `TD-013`
  - 时间：2026-03-13
  - 任务：Task 06
  - 问题：`device_open` 的 Android 稳定化逻辑落在 `tools/device_harness.py`，而 `tools/mcp_server.py` 的 `device_open` 仍直接做一次 `driver.preflight()`；同一 open 行为因入口不同而出现不同判定路径。
  - 影响：CLI 与 MCP 对同一 app launch / bridge readiness 可能给出不同结论，也违反了 `tools -> harness/*` 单向编排边界与“平台差异只在 adapter / bridge 层”的约束。
  - 复现：`rg -n "_retry_android_preflight|monkey returned 251|preflight = driver.preflight\\(\\)" /Users/josh_folder/scaffold/tools/device_harness.py /Users/josh_folder/scaffold/tools/mcp_server.py`
  - 下一步：把 open retry、`monkey` `251` 分类和 bridge-ready 判定下沉到 `harness/driver/android.py` 或共享 harness helper，让 CLI / MCP 只消费统一结果。

- `TD-014`
  - 时间：2026-03-13
  - 任务：Task 06
  - 问题：selector drift 后的“补抓 full snapshot 再重试”逻辑同时出现在 `tools/device_harness.py` 和 `tools/mcp_server.py`，没有收敛到 `harness/driver/device_bridge.py`。
  - 影响：工具层开始承载交互语义；任何新入口如果没复制这段逻辑，就会得到不同的 press / fill 行为，增加回归面。
  - 复现：`rg -n "selector_drift|full_snapshot = .*snapshot\\(" /Users/josh_folder/scaffold/tools/device_harness.py /Users/josh_folder/scaffold/tools/mcp_server.py /Users/josh_folder/scaffold/harness/driver/device_bridge.py`
  - 下一步：把 selector refresh/retry policy 合并进 `DeviceHarness.interact()` 或其共享 helper，工具层只负责参数组装与结果透传。

- `TD-015`
  - 时间：2026-03-13
  - 任务：Task 06
  - 问题：`tools/mcp_server.py` 的 `device_page_map` / `device_element_dictionary` 把 `android_accessibility_bridge`、`live_semantics_ready`、`degraded_reasons` 这类 Android / rollout 专属诊断直接暴露进稳定 MCP 结构化返回。
  - 影响：稳定 screen introspection 接口被 Android 细节和临时 live rollout 判定绑住，后续 iOS 或其它 capture source 会被天然视为 degraded，边界不再清晰。
  - 复现：`rg -n "android_accessibility_bridge|live_semantics_ready|degraded_reasons|recommended_lookup_fields" /Users/josh_folder/scaffold/tools/mcp_server.py`
  - 下一步：保留通用 snapshot metadata 在 harness snapshot payload；把 rollout readiness / degraded 判定收回到 `tools/live_android_validation.py` 这类专项验证入口。

- `TD-016`
  - 时间：2026-03-13
  - 任务：Task 06
  - 问题：Harmony app 的聚焦验证被代码生成产物缺失阻塞。`flutter test test/features/search/presentation/pages/search_page_test.dart` 编译时找不到 `todo_calendar_page/state.freezed.dart` 与 `todo_task_block/state.freezed.dart`。
  - 影响：Task 06 无法对 route/search 真实依赖图跑完更贴近 live rollout 的 widget test，只能退回到 navigation 语义专项与 analyze 最小集。
  - 复现：`cd /Users/josh_folder/harmony/app && flutter test test/features/search/presentation/pages/search_page_test.dart`
  - 状态更新（2026-03-13 / Task 09）：`todo_calendar` 侧缺失的 3 个 `state.freezed.dart` 已恢复，原始报错不再是首个编译阻塞点。
  - 状态更新（2026-03-13 / Task 14）：在 clean integration worktree 上基于 `d29f3d44` 重新 cherry-pick Task 02 后，`flutter test test/features/search/presentation/pages/search_page_test.dart` 与 `flutter analyze lib/features/search/presentation/pages/search_page` 仍首先暴露 `lib/core/time/time_models.freezed.dart`、`lib/features/items/domain/entities/item.freezed.dart`、`lib/features/search/presentation/pages/search_page/state.freezed.dart`、`lib/features/calendar/presentation/components/calendar_component/state.freezed.dart` 及多处 `*.g.dart` 缺失，说明当前阻塞仍是整仓 codegen 缺口而非 Task 02 clean slice 本身。
  - 状态更新（2026-03-13 / Task 12）：已在 `/Users/josh_folder/worktrees/harmony-task12-codegen/app` 完成整仓 `build_runner` 恢复，并同步移除两层 `.gitignore` 中对 `*.g.dart` / `*.freezed.dart` 的忽略规则。
  - 状态更新（2026-03-13 / Task 16）：已在 `/Users/josh_folder/worktrees/harmony-task16-codegen-integration` 基于 `develop-whc` clean baseline cherry-pick `5fe9b261`，落地为 `68b6c0c1 chore(codegen): restore tracked generated outputs`；指定验证中 `flutter test test/features/search/presentation/pages/search_page_test.dart` 继续通过，`flutter analyze lib/features/search lib/features/todo_calendar` 也仍只剩 5 个普通 warning，没有再出现缺失 `part` / `uri_does_not_exist`。
  - 当前状态：代码生成阻塞已解除。`flutter analyze lib/features/search lib/features/todo_calendar` 不再报缺失 `part`/`uri_does_not_exist`，当前只剩 5 个 warning；`flutter test test/features/search/presentation/pages/search_page_test.dart` 也已恢复为通过。
  - 下一步：把剩余 `unused_catch_stack` / `unused_local_variable` / `unused_import` warning 作为普通代码质量问题处理；`todo_calendar` 聚焦测试当前暴露的是真实断言失败，不再属于 `TD-016` 范畴。

- `TD-009`
  - 时间：2026-03-13
  - 任务：Task 03
  - 问题：按任务要求在 `/Users/josh_folder/harmony/app` 执行聚焦 `flutter test` / `flutter analyze` 时，`todo_calendar` 相关生成文件缺失，`state.freezed.dart` 等 `part` 目标不存在，导致 search / todo_calendar 相关测试与分析无法在当前工作树通过。
  - 影响：Task 03 已完成 scaffold 侧 live flow 稳定化，但 app-side 的必跑 Flutter 校验被工程状态阻塞，不能把失败归因到本次 scaffold 改动。
  - 复现：`cd /Users/josh_folder/harmony/app && flutter test test/app/navigation/foreground_screen_semantics_test.dart test/features/search/presentation/pages/search_page_test.dart test/features/todo_calendar/presentation/pages/todo_calendar_page/calendar_interaction_test.dart`
  - 复现：`cd /Users/josh_folder/harmony/app && flutter analyze lib/app/navigation lib/features/search lib/features/todo_calendar`
  - 状态更新（2026-03-13 / Task 09）：`lib/features/todo_calendar/**/state.freezed.dart` 缺件已恢复，Task 03 当时命中的首层阻塞已解除。
  - 状态更新（2026-03-13 / Task 12）：Task 03 当时遇到的整仓代码生成缺口已通过整仓 `build_runner` 恢复消除；search / todo_calendar 的聚焦命令现在可以进入真实测试逻辑。
  - 当前状态：底层 codegen blocker 已解除；Task 03 自身是否全绿，需要后续按它原始命令集补跑确认，但不再会被 `*.freezed.dart` / `*.g.dart` 缺件卡住。
  - 下一步：按 Task 03 原始要求重跑 `test/app/navigation/foreground_screen_semantics_test.dart` 联合校验，把剩余结果归因到 app/scaffold 真实行为，而不是工程缺件。

- `TD-020`
  - 时间：2026-03-13
  - 任务：Task 12
  - 问题：Task 12 完成整仓 codegen 恢复后，mandatory validation 不再卡在缺失生成文件，但 `flutter test test/features/todo_calendar/presentation/pages/todo_calendar_page/calendar_interaction_test.dart` 仍在第 489 行断言失败，`todoState.incompleteTodos.length` 期望 `1`、实际为 `0`；同时 `flutter analyze lib/features/search lib/features/todo_calendar` 仍返回 5 个 warning。
  - 影响：`TD-009` / `TD-016` / `TD-018` 对应的 codegen 阻塞已解除，但 Task 12 的 mandatory validation 还不是全绿；剩余失败已经是普通逻辑/代码质量问题。
  - 复现：`cd /Users/josh_folder/worktrees/harmony-task12-codegen/app && flutter test test/features/todo_calendar/presentation/pages/todo_calendar_page/calendar_interaction_test.dart`
  - 复现：`cd /Users/josh_folder/worktrees/harmony-task12-codegen/app && flutter analyze lib/features/search lib/features/todo_calendar`
  - 状态更新（2026-03-13 / Task 16）：在 clean integration worktree `/Users/josh_folder/worktrees/harmony-task16-codegen-integration/app` 上复现相同剩余结果：`calendar_interaction_test.dart` 仍在第 489 行断言失败（`todoState.incompleteTodos.length` 期望 `1`、实际 `0`），`flutter analyze lib/features/search lib/features/todo_calendar` 仍返回相同 5 个 warning，说明剩余问题已经与 codegen 集成解耦。
  - 状态更新（2026-03-13 / Task 21）：在 dedicated merge worktree `/Users/josh_folder/worktrees/harmony-task21-codegen-merge/app` 与真实 `develop-whc` worktree `/Users/josh_folder/javis_agent/app` 上，基于已落地的 codegen slice `e9cee441` 重新执行完全相同的 focused validation：`flutter test test/features/search/presentation/pages/search_page_test.dart`、`flutter test test/features/todo_calendar/presentation/pages/todo_calendar_page/calendar_interaction_test.dart`、`flutter analyze lib/features/search lib/features/todo_calendar` 均通过，`flutter analyze` 返回 `No issues found!`
  - 当前状态：已解除。`TD-020` 不再是 Task 21 的 blocker，也不再是当前 `develop-whc` 基线上的已知复现问题。
  - 下一步：关闭该债项；若后续 search/todo focused validation 再次失败，应基于新的复现条件重新建债。

- `TD-021`
  - 时间：2026-03-13
  - 任务：Task 19
  - 问题：指定 worktree `/Users/josh_folder/worktrees/harmony-task19-post-nav-screen` 的 `.git` 指向 `/Users/josh_folder/harmony/.git/worktrees/harmony-task19-post-nav-screen`，但本机不存在 `/Users/josh_folder/harmony`，导致该目录不是可用 git worktree。
  - 影响：Task 19 的代码修改和 Flutter 验证已经完成，但无法在该目录执行 `git status` / `git commit` / 后续 `develop-whc` 集成操作；当前 slice 只能以文件级变更存在，不能产出要求中的本地提交。
  - 复现：`git -C /Users/josh_folder/worktrees/harmony-task19-post-nav-screen status`
  - 下一步：先从真实 Harmony 仓库重新创建同名 worktree，或修复其 git common dir 指针后，再把本次 Task 19 变更 cherry-pick / apply 进去并完成非交互提交。

- `TD-022`
  - 时间：2026-03-18
  - 任务：Manual memo-source deletion probe
  - 问题：`device_page_map` 仍把轻量交互快照的第一个元素当成页面根。当前实现同时固定走 `interactive=True, compact=True`，而 Android 轻量快照会先过滤成 `interactive_only` 节点并把 `root` 重写成第一个幸存交互节点。
  - 影响：工具层会把 `record_list.add_button`、`todo_calendar.task_block.*` 这类交互节点误报成当前页根，导致页面识别和后续动作编排漂移；本次删除验证里进入 `item_detail` 后，`device_page_map` 仍多次报告 `record_list` 或其它错误根。
  - 复现：`python3 - <<'PY' ... execute_tool('device_page_map', {'session_file': session, 'refresh': True}) ... PY`，以及 `sed -n '548,606p' /Users/josh_folder/scaffold/tools/mcp_server.py`、`sed -n '115,140p' /Users/josh_folder/scaffold/harness/driver/android.py`
  - 下一步：让 `device_page_map` 改为从保留 page root 的 operability snapshot 派生，优先使用 `screen.<screen_id>` 或 bridge `root`，禁止把 `elements[0]` 当作健康语义路径下的 page root。

- `TD-023`
  - 时间：2026-03-18
  - 任务：Manual memo-source deletion probe
  - 问题：`device_press` / `device_fill` 仍然是“命令成功即返回”，没有统一的 post-action semantic settlement。当前逻辑只在成功后清空 snapshot cache，不等待 page identity、target availability 或 text visibility 稳定。
  - 影响：tap 或 fill 成功并不代表 UI 已进入目标页面或目标值已可见。本次验证里点击 `record_list.search_bar` 后，`device_fill(search.query_input, ...)` 仍命中 `selector_drift`；进入 `item_detail` 后，`device_page_map` 和 `device_find` 也可能短时间停留在旧页面语义。
  - 复现：`sed -n '1088,1185p' /Users/josh_folder/scaffold/tools/mcp_server.py`，以及 `python3 - <<'PY' ... execute_tool('device_press', ...); execute_tool('device_page_map', ...); execute_tool('device_fill', ...) ... PY`
  - 下一步：把 `device_open` 已有的 semantic settlement 模型扩展到 `device_press` / `device_fill`，让工具在返回前确认 page identity 或 target visibility 已稳定，而不是只依赖一次 adb 命令成功。

- `TD-024`
  - 时间：2026-03-18
  - 任务：Manual memo-source deletion probe
  - 问题：`scaffold` 底层 AndroidDriver 已支持 `swipe`，但公开 CLI 与 MCP 工具层没有稳定暴露 `device_swipe` 或同等级手势接口。
  - 影响：像 `Dismissible` 左滑删除、横向 reveal action、列表拖动这类真实业务操作，无法只通过公开 tool surface 完成。此次删除 `Source` record 时，最终只能直接调用 `AndroidDriver.interact({'action':'swipe', ...})` 绕过 CLI/MCP 公共接口。
  - 复现：`sed -n '343,375p' /Users/josh_folder/scaffold/harness/driver/android.py` 对比 `sed -n '500,560p' /Users/josh_folder/scaffold/tools/device_harness.py` 与 `sed -n '1380,1468p' /Users/josh_folder/scaffold/tools/mcp_server.py`
  - 下一步：在 CLI 和 MCP 同时增加受约束的手势接口，至少覆盖 `swipe`，并把它纳入同样的 selector、settlement、diagnostics 语义，而不是要求调用方降级为裸坐标 adb。

- `TD-025`
  - 时间：2026-03-18
  - 任务：Manual memo-source deletion probe
  - 问题：app 侧 `item_detail` 仍缺少删除链路所需的关键语义目标。`item_detail.record_row.{recordId}` 已有语义包裹，但默认详情页 AppBar 返回按钮没有 canonical semantic id，记录删除动作只存在于 `Dismissible` 手势里，没有独立的 semantic delete target。
  - 影响：AI 或 harness 可以识别“这是一条 record row”，但不能稳定识别“返回上一页”或“删除这条记录”的正式语义动作。本次删除验证必须借助 `uiautomator dump` 补看原生树，并用 driver 直接发 swipe，而不是通过 app-owned semantic selectors 完整闭环。
  - 复现：`sed -n '20,34p' /Users/josh_folder/javis_agent/app/lib/features/items/presentation/adapters/record_list_adapter.dart`、`sed -n '24,34p' /Users/josh_folder/javis_agent/app/lib/features/items/presentation/components/record_item/view.dart`、`sed -n '155,176p' /Users/josh_folder/javis_agent/app/lib/features/items/presentation/pages/item_detail_page/view.dart`、`sed -n '138,149p' /Users/josh_folder/javis_agent/app/lib/core/ui_semantics/semantic_ids.dart`
  - 下一步：为 `item_detail` 默认详情页补 canonical back semantic id，并为 record 删除链路补稳定的 semantic action surface；如果继续保留 `Dismissible` 交互，也要让删除动作在 bridge 导出里可见，而不是只存在于手势副作用里。

## Resolved Items

- `TD-001`
  - 时间：2026-03-13
  - 任务：Task 07
  - 问题：`develop-whc` 原本不存在，已本地创建为滚动合并目标，但尚未切换为主工作分支。
  - 处理：已新增独立集成 worktree `/Users/josh_folder/worktrees/scaffold-develop-whc-rollout`，直接 checkout `develop-whc`，后续滚动合并不再依赖切换当前脏 worker worktree。
  - 结果：`develop-whc` 现在有可直接接入的小型 slice 落点；当前调度仍可继续使用 `worker-e/scaffold-bridge-consumption-20260312-r2` 观察并整理。

- `TD-018`
  - 时间：2026-03-13
  - 任务：Task 12
  - 问题：Harmony app 的 repo root 与 `app/.gitignore` 同时忽略 `*.g.dart` / `*.freezed.dart`，但仓库里又已存在少量已跟踪生成文件，导致 focused Flutter 验证依赖“本地是否恰好跑过 codegen”的不稳定工程状态。
  - 处理：在 `/Users/josh_folder/worktrees/harmony-task12-codegen` 与 `/Users/josh_folder/worktrees/harmony-task12-codegen/app` 移除对应忽略规则，并执行 `dart run build_runner build --delete-conflicting-outputs` 恢复整仓输出。
  - 结果：本次恢复了 `39` 个缺失生成文件；`flutter test test/features/search/presentation/pages/search_page_test.dart` 已通过，`flutter analyze lib/features/search lib/features/todo_calendar` 也不再被 codegen 缺件阻塞。剩余 `todo_calendar` 失败是断言问题，不属于 codegen policy debt。

- `TD-003`
  - 时间：2026-03-13
  - 任务：Task 15
  - 问题：`lib/features/search/presentation/pages/search_page/effect.dart` 的两个 `unused_catch_stack` warning 会污染 search 相关 focused analyze 输出。
  - 处理：去掉 `_loadSuggestions()` 与 `_performSearch()` 里未使用的 `stackTrace` 绑定，保持异常分支行为不变。
  - 状态更新（2026-03-13 / Task 17）：原分配目录 `/Users/josh_folder/worktrees/harmony-task17-search-warning-integration` 实际是失联的旧拷贝，已从健康仓库 `/Users/josh_folder/javis_agent` 重新建成真实 `develop-whc` worktree 后复核；`915fadd5 修复了info级别的错误` 已是当前 `develop-whc` 的祖先提交，并负责把目标文件中的两个 `catch (error, stackTrace)` 收敛为 `catch (error)`，因此不需要再额外 cherry-pick `b5751f04` 的等价变更。
  - 结果：`TD-003` 已在真实 `develop-whc` 基线上确认关闭。Task 17 worktree 上 `flutter analyze lib/features/search/presentation/pages/search_page` 与 `flutter test test/features/search/presentation/pages/search_page_test.dart` 均已通过；此前“会先被 codegen 阻塞”的结论已过时，不再适用当前基线。

- `TD-020`
  - 时间：2026-03-13
  - 任务：Task 12 / Task 21
  - 问题：Task 12 codegen 恢复后曾暴露 `todo_calendar` 断言失败与 5 个 warning。
  - 处理：Task 21 在真实 `develop-whc` 基线上重新执行 focused validation，`search_page_test.dart`、`calendar_interaction_test.dart` 与 `flutter analyze lib/features/search lib/features/todo_calendar` 均通过。
  - 结果：`TD-020` 已在当前真实 `develop-whc` 基线上确认关闭。
