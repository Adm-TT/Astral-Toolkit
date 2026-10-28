"""联网下载的公共小工具：请求时说明「可以发压缩过的数据」，收到后自己解压

几个数据源（scmdb、UEX、starmap、汉化盒子、scl）都支持 gzip，JSON 压缩后通常只剩 1/5~1/10，
在中国大陆这种访问国外服务器慢的网络下，下载时间按比例缩短。
"""
import gzip
import urllib.request
import zlib


def read(req, timeout=60):
    """req 可以是网址或 urllib Request；返回解压好的原始字节"""
    if isinstance(req, str):
        req = urllib.request.Request(req)
    if not req.has_header("Accept-encoding"):
        req.add_header("Accept-Encoding", "gzip, deflate")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return decode(r.read(), r.headers.get("Content-Encoding"))


def decode(body, encoding):
    enc = (encoding or "").lower()
    if "gzip" in enc:
        return gzip.decompress(body)
    if "deflate" in enc:
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -15)
    return body
