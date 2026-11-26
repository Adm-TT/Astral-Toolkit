"""游戏右上角调试信息（r_DisplayInfo）在截图上的默认范围。

导航读位置（navigation/displayinfo）按它截图，悬浮窗（app/overlay）按它让开、不把文案窗盖在上面。
实际范围先看区域文件里的 KEY（读屏开发工作台里画），没有才用 REGION。
原来只在 navigation/displayinfo.py，2026-11-26 拆领域互引时挪到公共底座，悬浮窗不再引用导航。
"""

KEY = "nav.displayinfo"
REGION = (
    0.66,
    0.0,
    1.0,
    0.22,
)  # 右上角：左、上、右、下（占屏幕比例）；只截用得到的几行，识别快一半
