# ARCHITECTURE

这个文档只描述“稳定、不常变”的架构事实，主要回答两类问题：
- 做 X 应该改哪里？
- 我正在看的这个模块是干嘛的？

## 1) 做 X 应该改哪里？

- 新增/修改场景 DSL 字段或动作：`harness/driver/dsl.py` + `tests/test_dsl.py`
- 让某个动作在 Android/iOS 上真正执行：`harness/driver/android.py` 或 `harness/driver/ios.py`
- 修改跨平台交互语义（快照/diff/verify/replay）：`harness/driver/device_bridge.py`
- 调整选择器解析或抗漂移策略：`harness/driver/selectors.py` + `tests/test_selectors.py`
- 变更运行证据结构（events/snapshots/diffs/summary）：`harness/evidence/bus.py`
- 修改 oracle 评估逻辑：`harness/oracle/evaluator.py` + `rules/oracle_rules.json`
- 调整失败打包内容：`harness/triage/bundle.py` + `tools/package_failure.py`
- 调整“跑场景”的主流程：`tools/run_scenario.py`
- 调整回放与一致性评分：`tools/replay_run.py`
- 调整仓库级检查门禁：`tools/check_repo.py` 与 `Makefile`

## 2) 模块是干嘛的？（代码地图）

### 输入层（声明）

- `scenarios/`：可执行场景（DSL JSON）
- `rules/oracle_rules.json`：oracle 判定阈值与开关
- `config/`：设备和环境模板配置

### 执行层（harness）

- `harness/driver/dsl.py`
  负责解析并校验场景；核心类型是 `Scenario`。
- `harness/driver/device_bridge.py`
  平台无关的设备桥抽象 `DeviceHarness`；定义统一能力：`snapshot / diff / interact / verify / replay`。
- `harness/driver/android.py`, `harness/driver/ios.py`
  平台适配层；把统一动作编译为平台命令。
- `harness/driver/selectors.py`
  元素 `ref`/`anchor` 生成与选择器解析；处理 selector drift。
- `harness/evidence/bus.py`
  证据总线；把事件与快照/差异写入 `runs/<run-id>/`。
- `harness/oracle/evaluator.py`
  读取 run 产物并按规则计算 pass/fail，输出 `oracle_report.json`。
- `harness/triage/bundle.py`
  失败归档打包（`failure_bundle.tar.gz`）。

### 入口层（tools）

- `tools/run_scenario.py`：单次场景执行主入口
- `tools/evaluate_run.py`：oracle 评估入口
- `tools/replay_run.py`：回放与结构一致性比较
- `tools/update_selectors.py`：基于最新快照修复漂移 selector
- `tools/device_harness.py`：交互式统一 CLI（open/snapshot/press/fill/verify）
- `tools/check_repo.py`：仓库完整性 + smoke 可执行性检查

### 验证层

- `tests/`：DSL、selector、device harness 的行为回归测试

## 3) 模块关系与边界

```text
scenarios/ + config/ + rules/
          |
          v
tools/*.py (orchestration)
          |
          v
harness/driver (dsl + bridge + adapters + selectors)
          |
          v
harness/evidence (write runs/<run-id>/ artifacts)
          |
          +--> harness/oracle (evaluate run artifacts)
          +--> harness/triage (package failed run)
```

边界约束：
- `tools/` 负责编排，不承载核心判定逻辑。
- 平台差异只放在 `harness/driver/android.py` 与 `harness/driver/ios.py`。
- `oracle` 和 `triage` 只消费 run 产物，不直接驱动设备。

## 4) 架构不变量（必须保持）

- 依赖方向保持单向：`tools -> harness/*`，避免反向依赖。
- 场景格式变更必须同步更新：`harness/driver/dsl.py` 与 `tests/`。
- 每个场景步骤都要能产出证据（events + before/after/diff）到 `runs/<run-id>/`。
- 不支持的动作必须显式报错，不能静默跳过。
- 失败运行必须可由 `tools/package_failure.py` 打包。
- oracle 至少可评估一条断言路径（assertion path）。
