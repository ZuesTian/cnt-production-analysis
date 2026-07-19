# 碳纳米管生产数据分析系统

碳纳米管（CNT）生产线数据综合分析工具，包含厂内离线 Web 2.0 工作台、桌面 GUI 和 CLI。Web 端支持不可变数据版本、质量门禁、班次/炉日双粒度、交互图表、后台报表及发布回滚。

**在线前端：** https://zuestian.github.io/cnt-production-analysis/
> GitHub Pages 托管 Vue 前端，FastAPI/SQLite 后端部署在独立 HTTPS 服务。在线环境使用账号登录和限时签名会话；除健康检查与登录接口外，API 均要求有效的 Bearer 会话。

## 快速开始

### 方式一：Web 2.0 工作台（厂内局域网推荐）

```bash
pip install -r web_app/requirements_web.txt
python web_app/run_server.py
```

浏览器访问 `http://服务器地址:8000`。启动时会自动执行 Alembic 数据库升级；前端生产构建已经包含在 `web_app/frontend/dist`，运行服务器不需要 Node.js、CDN 或外网。数据默认写入 `web_app/data`，也可通过 `CNT_DATA_DIR` 指定持久化目录。

跨域部署时可配置：

```bash
CNT_ALLOWED_ORIGINS=https://zuestian.github.io
CNT_AUTH_USERS_B64=<Base64 编码的账号 JSON，密码字段必须是 PBKDF2 哈希>
CNT_AUTH_SECRET=<至少 32 字节的随机会话签名密钥>
CNT_AUTH_TOKEN_TTL_SECONDS=43200
```

账号 JSON 是由 `username`、`display_name`、`password_hash` 组成的数组。可用 `web_app.auth.hash_password()` 生成加盐哈希；账号配置与签名密钥只放在服务器的 `0600` 环境文件中，不得提交到仓库。`CNT_API_TOKEN` 仅保留为未配置账号登录时的兼容回退方案。

重新开发前端时：

```bash
cd web_app/frontend
npm install
npm run generate:types   # 本地 API 在 8765 端口时生成 OpenAPI 类型
npm run build
```

### 方式二：打包版（无需 Python）

1. 下载 `dist/碳纳米管生产数据分析.exe`
2. 将生产数据文件放在 exe 同目录下（支持 `.xlsx / .xlsm / .xls / .ods / .csv / .tsv / .txt`）
3. 双击 exe 启动 GUI

### 方式三：桌面源码运行

```bash
pip install -r requirements.txt
python gui_app.py
```

### 方式四：命令行

```bash
python analysis.py --all                                    # 全部分析
python analysis.py --furnace E01 E02 --daily --monthly      # 指定炉子
python analysis.py --anomaly                                # 异常检测
python analysis.py --list-furnaces                          # 列出所有炉号
```

## 功能模块

### 趋势图

| 图表 | 说明 |
|------|------|
| 每日趋势图 | 全区日产量柱状图 + 反应/故障/空烧/降清时间折线 |
| 每月趋势图 | 同上按月聚合 |
| 炉子级统计图 | 月度平均反应时间 + 平均产率双面板 |

### 周期分析

| 图表 | 说明 |
|------|------|
| 周期分布 | 2×2 面板：反应时间直方图、周期天数直方图、产率直方图、统计摘要 |
| 周期热力图 | 炉号×日期，颜色=反应时间，直观发现异常模式 |

**周期算法**：每条班次记录 = 一次启停周期（启动→运行→关闭）。空烧降清+故障累计 ≥20h 标记周期边界。

### 产率对比

| 图表 | 说明 |
|------|------|
| 炉均产率 | 横向柱状图：每个炉子的平均产率排名 |
| 每日产率 | 多炉每日产率折线对比（炉子多时建议用热力图） |
| 三维产率 | 3D 柱状图：日期×炉号×产率，支持高亮炉号/日期 |
| 产率热力图 | 炉号×日期，红绿渐变色=产率高低，替代拥挤折线 |

### 统计与排名

| 功能 | 说明 |
|------|------|
| 前后20%排名 | 每月独立排名，5项指标分别取前后20%，按指标分Tab展示 |
| 单炉趋势图 | 单炉每日产量+产率（7日均线+线性趋势线+异常标记+周期边界） |

### 异常检测

基于炉号内 2σ + 最低产率阈值（可配置）的双规则机制，自动标记异常低产班次。该功能明确属于规则异常，不是预测模型。

## GUI 界面

```
┌─ 左侧控制面板 ───────────────────┬─ 右侧结果区 ──────────────────┐
│ 📂 数据源                        │  周期数  炉号  日期  产线    │
│ 📊 分析内容 [可折叠 ▾]           │ ┌──────────────────────────┐ │
│    ☑ 炉子级统计                  │ │ [趋势图预览] [日志] [输出] │ │
│    ☑ 每日汇总                    │ │                          │ │
│ 📆 日期范围 [可折叠 ▾]           │ │  预览图 / 产率对比 /     │ │
│ 🔧 炉号范围                      │ │  前后20%排名              │ │
│    ○ 全区  ○ 自选               │ │                          │ │
│ [▶️ 运行分析]                    │ │  (自适应窗口大小)         │ │
│ [💾 导出报表] [📂 输出目录]      │ └──────────────────────────┘ │
└─────────────────────────────────┴────────────────────────────┘
```

### 操作流程

1. **加载数据** → 自动识别目录中的 Excel、ODS 或分隔文本文件
2. **选炉号** → 全区或自选（支持前缀匹配如 `E`、`11A`）
3. **勾选分析项** → 运行分析，结果暂存内存
4. **预览图表** → 点击预览按钮查看（纯内存生成，不写盘）
5. **导出报表** → 一次性批量写 Excel
6. **导出图表数据** → 每张图可单独导出原始数据为 Excel

## 配置文件

`config.yaml` 支持自定义列映射、产线规则、告警阈值：

```yaml
source_columns:
  date: 日期                 # → 可适配不同命名习惯
  furnace: 炉号
  reaction_time: 生产时间
  fault_time: 设备故障影响时间
  clean_empty_burn_time: 停机清理空烧
  output: 产量
  source_yield: 小时产能

production_lines:
  L3: {patterns: ["E","F","G","H","B"]}
  "11A": {patterns: ["11A"]}

team_aliases:
  "白班 张三": "白班张三"  # 仅做明确别名映射，不会自动模糊合并姓名

ranking:
  top_percent: 0.2

alert_thresholds:
  fault_warning_hours_per_day: 8
  fault_critical_hours_per_day: 12
  consecutive_fault_days: 2
  monthly_fault_hours_warning: 24
  min_yield_rate: 50
  anomaly_sigma: 2.0
```

## 数据格式

网页端和分析引擎支持 `.xlsx / .xlsm / .xls / .ods / .csv / .tsv / .txt`；网页端会将常见误写的 `.xlxs` 按 `.xlsx` 兼容处理，但仍会校验真实工作簿结构。还可直接粘贴从 Excel 复制的单元格区域；系统会识别制表符、逗号、分号或竖线，并在前 30 行自动寻找表头。

数据需包含以下列（列名可通过 config.yaml 自定义，并支持常见同义表头）：

| 列名 | 含义 | 示例 |
|------|------|------|
| 日期 | Excel 序列号或标准日期 | 46023 / 2026-01-01 |
| 班组 | 白班/夜班 | 白班 |
| 炉号 | 炉子编号 | E01, 11A17 |
| 生产时间 | 反应运行（小时） | 9.3 |
| 设备故障影响时间 | 故障停机（小时） | 2.5 |
| 停机清理空烧 | 空烧/降清（小时） | 1.0 |
| 产量 | 产量（kg） | 830 |
| 小时产能 | 产率（kg/h） | 89.2 |

> `停机清理空烧` 在内部只计入一项“清理/空烧时长”。旧 Excel 模板仍保留“降清时间”兼容列，但填 0，避免停机时长重复相加。

## 项目结构

```
碳纳米管生产数据分析/
├── analysis.py              # 核心数据分析引擎
├── gui_app.py               # GUI 启动入口
├── analysis_gui/            # tkinter 桌面 GUI 模块化包
│   ├── app.py               # 主应用类
│   ├── layout.py            # 界面布局与 UI 组件
│   ├── state.py             # 应用状态管理
│   ├── workflow.py          # 业务逻辑与分析工作流
│   ├── preview.py           # 图表预览窗口
│   ├── image_support.py     # 图片加载与自适应渲染
│   ├── constants.py         # 统一定义常量与枚举
│   ├── utility.py           # 界面相关工具函数
│   └── platform.py          # 操作系统级兼容处理
├── config.yaml              # 外部配置文件
├── web_app/                 # FastAPI + SQLite WAL + Vue 3 Web 工作台
│   ├── main.py              # 同源 API 与 SPA 托管
│   ├── models.py            # 数据版本、班次、作业、审计模型
│   ├── alembic/             # 数据库迁移
│   ├── frontend/            # Vue/TypeScript 源码与离线 dist
│   └── run_server.py        # 生产启动入口
├── requirements.txt         # Python 依赖
├── tests/
│   ├── test_analysis.py     # 核心功能单元测试
│   └── test_web_v2.py       # API、隔离、安全与发布回滚测试
├── dist/
│   └── 碳纳米管生产数据分析.exe   # 单文件打包（独立版）
└── README.md
```

## 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.13 | 运行环境 |
| tkinter | 桌面 GUI（支持 HiDPI） |
| pandas / numpy | 数据处理与统计 |
| matplotlib | 图表生成（统一样式系统） |
| openpyxl | Excel 读写与格式化 |
| PyYAML | 配置文件解析 |
| Pillow | 图片加载与自适应缩放 |
| PyInstaller + UPX | 单文件打包 |
| FastAPI / SQLAlchemy / SQLite WAL | Web API、版本持久化与并发读写 |
| Vue 3 / TypeScript / Vite | 响应式离线 SPA |
| Element Plus / ECharts 6 | 人体工学组件与无障碍交互图表 |

## License

MIT
