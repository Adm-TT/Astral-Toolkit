"""真 pytest 入口：同 tests/__init__.py，测试一律不往服务器发反馈"""

import os

os.environ["AT_FEEDBACK_OFF"] = "1"
