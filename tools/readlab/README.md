# 读屏开发工作台（只给开发用，不打包进 AT）

在本机浏览器里：看截图样本、画读屏区域并存进 `astral_toolkit/screen_regions.json`、点图试各读屏功能、批量跑样本出带框报告。截图不上传、不外发；服务只听 127.0.0.1。

## 起

```
.venv\Scripts\python.exe -X utf8 -m tools.readlab                # 自动开浏览器
.venv\Scripts\python.exe -X utf8 -m tools.readlab --samples D:\某个样本目录 --port 8765 --no-browser
```

不给 `--samples` 时用：`E:\Claude公主的书\项目资料\测试数据`、`tests\samples`、`tools\sample_sweep.py` 登记的截图来源（有的才用）。批量报告放在第一个样本根下的 `工作台报告\`。

## 用

- 左边选功能、选截图（上面的框能按文件名筛）。
- 右边选一个区域，在图上拖框就是画它；拖框里面是挪，拖四个角是改大小。「种类」分要认 / 排除。区域按**这张截图的屏幕比例**存，别的比例没画过时借最接近的那条显示（虚线）。
- 「存区域」：存进区域文件。两个页面同时改时后存的会被拒，刷新再改。改完要跑一遍「批量查」，看认得有没有变差。
- 「点图就试」开着时点截图：当场跑这个功能，结果框叠在图上（绿 = 认到、红 = 没认到）。
- 「批量查」：跑左边列表里筛出来的全部样本，能看进度、能取消，跑完点链接看报告。

## 加一个新的读屏功能

在 `features.py` 里写 `try_at(img, point) -> Result` 和 `batch(img) -> Result`，登记进 `FEATURES`，`regions` 写它用到的区域键。代码里取区域用 `screen_regions.frac(键, 默认值, img.size)`。

## 画框组件

本来打算用开源的 Annotorious；这台电脑没有 Node、云端也装不了，第一版是自己写的一个简单矩形编辑器（`static/app.js`，画 / 挪 / 改大小）。以后要换成 Annotorious，只改 `app.js` 里「拖框」那一段。
