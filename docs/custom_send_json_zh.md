# 自定义发送词条 JSON 格式

COMTool 的“自定义发送”支持从 JSON 文件导入，也支持导出为 JSON 文件。导出的默认格式是一个数组，每个数组元素代表一条自定义发送词条。

也可以导入一个包含 `customSendItems` 字段的对象，程序会读取其中的数组。

## 数组格式

```json
[
  {
    "text": "AT+RST",
    "remark": "复位",
    "icon": "fa.refresh",
    "highlight": true,
    "color": "#ffc107"
  },
  {
    "text": "AT+GMR",
    "remark": "版本",
    "icon": "fa.info-circle",
    "highlight": false,
    "color": ""
  }
]
```

## 对象格式

```json
{
  "customSendItems": [
    {
      "text": "AT",
      "remark": "握手",
      "icon": "fa.send",
      "highlight": false,
      "color": ""
    }
  ]
}
```

## 字段说明

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `text` | string | 是 | 点击词条按钮时发送的内容。 |
| `remark` | string | 否 | 词条按钮上显示的标记，建议写成便于搜索的短名称。 |
| `icon` | string | 否 | 词条按钮使用的 QtAwesome 图标名，例如 `fa.send`、`fa.refresh`。为空时默认使用 `fa.send`。 |
| `highlight` | boolean | 否 | 兼容旧格式。为 `true` 且没有设置 `color` 时，会使用默认高亮色。 |
| `color` | string | 否 | 词条按钮颜色，使用 `#RRGGBB` 格式。为空字符串表示不设置自定义颜色。 |

## 兼容规则

- 导入旧版本的纯字符串数组时，程序会把每个字符串作为 `text` 处理。
- 缺失的 `remark`、`color` 会按空字符串处理。
- 缺失的 `icon` 会按 `fa.send` 处理。
- 如果 `highlight` 为 `true` 且 `color` 为空，会自动设置为 `#ffc107`。
- 批量编辑颜色或图标后，导出的 JSON 会保存最新结果。
