# 参数化异形轮廓（开发中）

本阶段新增三种由毫米尺寸直接构造的闭合二维轮廓，不调用 AutoCAD 动态块，也不缩放 DXF 图块来冒充参数化几何。

`ModuleParameters.front_outline` 和 `board_face_outline` 分别控制正面、夹板面。两者互不继承；未指定时沿用原有普通/正敲/侧敲与夹板面模板逻辑。夹板是否存在仍由独立的 `BoardParameters.exists` 决定，无夹板时照常绘制夹板面并标「无夹板」。

## JSON 输入

```json
{
  "module_id": "I1",
  "front_width_mm": 300,
  "front_height_mm": 230,
  "board_face_width_mm": 300,
  "board_face_height_mm": 230,
  "front_outline": {
    "kind": "corner-cut",
    "feature_width_mm": 40,
    "feature_height_mm": 30
  },
  "board_face_outline": {
    "kind": "edge-notch",
    "feature_width_mm": 40,
    "feature_height_mm": 30,
    "offset_mm": 60
  }
}
```

坐标原点在左上，X 向右、Y 向下。全部尺寸为毫米。

| `kind` | 几何定义 | 必填特征 |
| --- | --- | --- |
| `corner-cut` | 右上角从 `(W−a, 0)` 斜切到 `(W, b)` | 宽 `a`、高 `b` |
| `edge-notch` | 顶边从左侧偏移 `d` 后向内开宽 `a`、深 `b` 的槽 | `a`、`b`、偏移 `d` |
| `step` | 右上角宽 `a`、高 `b` 的直角台阶 | `a`、`b` |

`mirror_x: true` 可将轮廓水平镜像。宽和高必须严格小于所在面的整体宽高；开槽必须严格落在顶边内部。异形特征尺寸从同一组参数生成轮廓和尺寸标注。锚固件中心落在夹板面被切除区域，或正面投影落在正面被切除区域时，生成会报出模块编号并停止。

## 当前边界

- 本阶段的异形正面仅与「普通」及「侧敲」组合；正敲正面异形的构造规则尚未确认，输入时明确报错。侧敲的侧面梯形仍由既有侧面参数生成。
- 这三种简单轮廓是新增的直接计算路径。原有的 15 种 DXF 夹板面模板仍是历史兼容路径，使用时会整体缩放，**不能视为已完成的参数化异形族**。同一模块不能同时指定非矩形模板与 `board_face_outline`。
- 圆弧、自定义闭合轮廓、组合异形、锚固件符号整体与孔槽的干涉检查、Excel/UI 异形编辑和黄金样板逐页比对仍待实现。
- 新轮廓尚未由用户确认对应的具体加工图族，不用于宣称 B1–B13 / S1–S4 已验收。

