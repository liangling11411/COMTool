# Protocol 多通道数据捕获脚本说明

协议页的 `Multi-channel Data Capture` 脚本不是完整插件，只需要在代码区定义表格、列、图表和 `parse(line, ctx)` 方法。

点击 `应用脚本` 会读取 `tables`、`columns`、`plots` 并更新查看窗口。点击 `启用捕获` 后按钮会变成 `暂停捕获`，暂停后可继续，`停止捕获` 会结束本次捕获会话。`清空折线图` 只清空曲线数据，不影响已捕获的表格数据。

## 基本结构

```python
import re

tables = [
    {"id": "BAT1", "title": "Battery 1"},
    {"id": "BAT2", "title": "Battery 2"},
]

columns = ["time", "voltage", "current", "temperature", "soc"]

plots = [
    {
        "title": "Voltage",
        "y": ["BAT1.voltage", "BAT2.voltage"],
    },
]

def parse(line, ctx):
    return None
```

## 添加表格

`tables` 决定弹窗里有多少个表格。每个表格至少需要一个 `id`。

```python
tables = [
    {"id": "sheet1", "title": "Sheet 1"},
    {"id": "sheet2", "title": "Sheet 2"},
]
```

脚本返回的数据通过 `table` 字段决定进入哪个表格：

```python
return {
    "table": "sheet1",
    "value": 12.3,
}
```

## 添加列

`columns` 是默认列顺序。如果 `parse()` 返回了新的字段，表格会自动新增列。

```python
columns = ["time", "voltage", "current", "temperature"]
```

系统会自动补充这些字段：

```text
time, unix_s, unix_ms, elapsed_s, elapsed_ms
```

`time` 的显示格式由界面里的时间格式选择决定。

## 添加折线图

`plots` 决定弹窗里有多少个图。每个图的 `y` 使用 `表格id.字段名` 引用数据。

```python
plots = [
    {
        "title": "Voltage",
        "y": ["BAT1.voltage", "BAT2.voltage"],
    },
    {
        "title": "Temperature",
        "y": ["BAT1.temperature", "BAT2.temperature"],
    },
]
```

图表 x 轴默认使用界面选择的字段，例如 `elapsed_s`、`elapsed_ms`、`unix_s` 或 `unix_ms`。

表格里只显示当前选择的 `time` 格式，不会额外显示 `unix_s`、`unix_ms`、`elapsed_s`、`elapsed_ms` 这些内部时间字段；这些字段仍可用于图表 x 轴。

## 解析单行数据

串口每收到一行文本，系统会调用：

```python
parse(line, ctx)
```

`line` 是当前串口文本行，不包含结尾换行符。`ctx` 包含当前时间和行号：

```python
ctx["time"]
ctx["unix_s"]
ctx["unix_ms"]
ctx["elapsed_s"]
ctx["elapsed_ms"]
ctx["line"]
```

## 返回规则

忽略普通日志：

```python
return None
```

返回一行数据：

```python
return {
    "table": "BAT1",
    "voltage": 4.102,
    "current": 0.532,
}
```

一行日志里解析出多路数据：

```python
return [
    {"table": "BAT1", "voltage": 4.102},
    {"table": "BAT2", "voltage": 4.098},
]
```

## 示例：每行一个电池

串口日志：

```text
init ok
BAT1 V=4.102 I=0.532 T=31.5 SOC=82
BAT2 V=4.098 I=0.529 T=31.2 SOC=81
ERROR something
```

脚本：

```python
import re

tables = [
    {"id": "BAT1", "title": "Battery 1"},
    {"id": "BAT2", "title": "Battery 2"},
]

columns = ["time", "voltage", "current", "temperature", "soc"]

plots = [
    {"title": "Voltage", "y": ["BAT1.voltage", "BAT2.voltage"]},
    {"title": "Current", "y": ["BAT1.current", "BAT2.current"]},
    {"title": "Temperature", "y": ["BAT1.temperature", "BAT2.temperature"]},
]

pattern = re.compile(
    r"BAT(?P<ch>[1-2])\s+V=(?P<voltage>-?\d+\.?\d*)\s+I=(?P<current>-?\d+\.?\d*)\s+T=(?P<temperature>-?\d+\.?\d*)\s+SOC=(?P<soc>-?\d+\.?\d*)"
)

def parse(line, ctx):
    m = pattern.search(line)
    if not m:
        return None
    return {
        "table": "BAT" + m.group("ch"),
        "voltage": float(m.group("voltage")),
        "current": float(m.group("current")),
        "temperature": float(m.group("temperature")),
        "soc": float(m.group("soc")),
    }
```

## 示例：一行包含多路数据

串口日志：

```text
BAT1:4.102,0.532,31.5,82 BAT2:4.098,0.529,31.2,81
```

脚本：

```python
import re

tables = [
    {"id": "BAT1", "title": "Battery 1"},
    {"id": "BAT2", "title": "Battery 2"},
]

columns = ["time", "voltage", "current", "temperature", "soc"]
plots = [{"title": "Voltage", "y": ["BAT1.voltage", "BAT2.voltage"]}]

pattern = re.compile(
    r"BAT(?P<ch>[1-2]):(?P<voltage>-?\d+\.?\d*),(?P<current>-?\d+\.?\d*),(?P<temperature>-?\d+\.?\d*),(?P<soc>-?\d+\.?\d*)"
)

def parse(line, ctx):
    rows = []
    for m in pattern.finditer(line):
        rows.append({
            "table": "BAT" + m.group("ch"),
            "voltage": float(m.group("voltage")),
            "current": float(m.group("current")),
            "temperature": float(m.group("temperature")),
            "soc": float(m.group("soc")),
        })
    return rows or None
```

## 常见错误

- `parse()` 没有定义：点击 Enable Capture 或 Test Script 会提示脚本错误。
- 返回 dict 但缺少 `table`：系统不知道写入哪个表格。
- `plots` 引用了不存在或非数字字段：该点会被跳过，不会导致程序崩溃。
- 普通 debug log 不应该抛异常，直接 `return None` 即可。

## 长时间运行和导出

捕获启动后，完整捕获结果会持续写入工作目录下的 `capture_data/capture_时间.db` SQLite 会话数据库。界面表格只保留最近的可视行数，折线图只保留最近的点数，避免长时间运行时 UI 内存持续增长。

停止捕获后再导出 CSV，程序会优先从 SQLite 会话数据库流式导出完整数据，而不是只导出界面上保留的最近几行。
