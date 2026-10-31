"""只读：解析 .soc 里嵌的 CryXmlB 块 → ElementTree"""
import struct, re
import xml.etree.ElementTree as ET


def parse_block(b, s):
    hdr = struct.unpack_from("<9I", b, s + 8)
    size, npos, ncnt, apos, acnt, cpos, ccnt, spos, ssize = hdr
    strs = b[s + spos: s + spos + ssize]

    def S(o):
        e = strs.find(b"\0", o)
        return strs[o:e].decode("utf-8", "replace")
    nodes = []
    for i in range(ncnt):
        tag, content, na, nc, parent, fa, fc, _r = struct.unpack_from("<IIHHIIII", b, s + npos + i * 28)
        nodes.append((tag, content, na, nc, parent, fa, fc))
    attrs = [struct.unpack_from("<II", b, s + apos + i * 8) for i in range(acnt)]
    childs = [struct.unpack_from("<I", b, s + cpos + i * 4)[0] for i in range(ccnt)]
    els = []
    for tag, content, na, nc, parent, fa, fc in nodes:
        el = ET.Element(S(tag))
        for k, v in attrs[fa: fa + na]:
            el.set(S(k), S(v))
        c = S(content)
        if c:
            el.text = c
        els.append(el)
    for i, (tag, content, na, nc, parent, fa, fc) in enumerate(nodes):
        for j in childs[fc: fc + nc]:
            els[i].append(els[j])
    return els[0], s + size


def blocks(path):
    b = open(path, "rb").read()
    out = []
    for m in re.finditer(rb"CryXmlB\0", b):
        try:
            root, _ = parse_block(b, m.start())
            out.append(root)
        except Exception as e:  # noqa
            pass
    return out


def entities(path):
    """→ [Entity Element]（每个块里的 Entity 节点）"""
    ents = []
    for r in blocks(path):
        for e in r.iter("Entity"):
            ents.append(e)
    return ents
