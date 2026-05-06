# 碳纳米管生产数据分析系统

碳纳米管（CNT）生产线数据综合分析工具，支持 L3 和 11A 产线的炉子级统计、每日/月汇总、异常检测、故障分析和故障预警。

## 功能

| 模块 | 说明 |
|------|------|
| 炉子级统计 | 反应周期明细、月度平均、每月前/后 20% 筛选 |
| 每日汇总 | 总产量、总反应/故障/空烧/降清时间 + 趋势图 |
| 每月汇总 | 同上按月聚合 + 趋势图 |
| 单炉趋势 | 每个炉子单独的每日趋势图（7 日均线 + 线性回归 + 异常标记） |
| 异常检测 | 3σ 原则 + 最低产率阈值，自动标记异常低产周期 |
| 故障分析 | 故障炉号排名、星期分布、热力图 |
| 故障预警 | 单日超阈值 / 连续故障 / 月累计超标 三级预警 |

## 快速开始

### 打包版本（推荐）

下载 `dist/碳纳米管生产数据分析.exe`，将生产数据 `.xlsx` 放在同目录下，双击运行。

### 源码运行

```bash
pip install -r requirements.txt
python gui_app.py
```

### 命令行

```bash
# 全部分析
python analysis.py --all

# 指定炉子
python analysis.py --furnace E01 E02 --daily --monthly

# 异常检测
python analysis.py --anomaly

# 故障分析
python analysis.py --fault-analysis --fault-warning
```

## 配置文件

`config.yaml` 支持自定义列映射、产线规则、告警阈值：

```yaml
source_columns:
  date: 日期
  furnace: 炉号
  ...

alert_thresholds:
  fault_warning_hours_per_day: 8
  anomaly_sigma: 2.0
  ...
```

## 技术栈

- Python 3.13 + tkinter 桌面 GUI
- pandas / numpy 数据处理
- matplotlib 可视化
- openpyxl Excel 报表
- PyInstaller + UPX 单文件打包

## 项目结构

```
├── analysis.py          # 分析引擎（68 个函数）
├── gui_app.py           # tkinter GUI（交互面板 + 三 Tab 预览）
├── config.yaml          # 外部配置
├── tests/               # pytest 测试
└── dist/                # 打包产物
```

## License

MIT
