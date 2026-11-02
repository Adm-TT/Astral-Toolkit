"""星际公民 MOLE 挖矿扫描助手 —— 计算核心"""

import os as _os

# numpy 自带的数学库（OpenBLAS）一加载就按 CPU 线程数给每个线程预留一大块内存：
# 32 线程的电脑上光这一项就占 740MB「提交内存」。我们只做小图片的简单运算，用不着多线程，限成 1 个。
# 必须在任何地方 import numpy 之前设好，所以放在包的最开头。
for _k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_k, "1")
