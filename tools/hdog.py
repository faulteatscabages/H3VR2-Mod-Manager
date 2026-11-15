"""Reader/writer for H3VR2 .hdog content packs.

Layout (little endian):
  b"HDOG" u8 version
  blobs...
  TOC: count x { u32 offset, u32 size, str7 name, 4-byte tag }
  u32 count, u32 toc_offset

str7 = .NET BinaryWriter string (7-bit varint length + utf8).
Tags seen: INFO (gzipped json manifest), UABP (bundle manifest bundle),
UABR (asset bundle), FMBK (FMOD bank).
"""
import struct, gzip, json, io


def _r7(b, p):
    n = s = 0
    while True:
        c = b[p]; p += 1
        n |= (c & 0x7F) << s; s += 7
        if c < 0x80:
            return n, p


def _w7(n):
    out = bytearray()
    while True:
        c = n & 0x7F; n >>= 7
        if n:
            out.append(c | 0x80)
        else:
            out.append(c); return bytes(out)


class Entry:
    __slots__ = ("name", "tag", "offset", "size", "data")

    def __init__(self, name, tag, offset=0, size=0, data=None):
        self.name, self.tag, self.offset, self.size, self.data = name, tag, offset, size, data

    def __repr__(self):
        return f"<{self.tag} {self.name} @{self.offset} {self.size}>"


class Hdog:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        self.f.seek(0, 2); end = self.f.tell()
        self.f.seek(0); head = self.f.read(5)
        assert head[:4] == b"HDOG", head
        self.version = head[4]
        self.f.seek(end - 8)
        count, toc = struct.unpack("<II", self.f.read(8))
        self.f.seek(toc); b = self.f.read(end - 8 - toc)
        p = 0; self.entries = []
        for _ in range(count):
            off, size = struct.unpack_from("<II", b, p); p += 8
            n, p = _r7(b, p); name = b[p:p + n].decode(); p += n
            tag = b[p:p + 4].decode(); p += 4
            self.entries.append(Entry(name, tag, off, size))
        assert p == len(b)
        self.by_name = {e.name: e for e in self.entries}

    def read(self, name):
        e = self.by_name[name]
        if e.data is not None:
            return e.data
        self.f.seek(e.offset); return self.f.read(e.size)

    def manifest(self):
        raw = gzip.decompress(self.read("manifest"))
        return json.loads(raw.decode("utf-8-sig"))

    def set(self, name, tag, data):
        if name in self.by_name:
            e = self.by_name[name]; e.data = data; e.tag = tag
        else:
            e = Entry(name, tag, data=data); self.entries.append(e); self.by_name[name] = e

    def set_manifest(self, obj):
        raw = b"\xef\xbb\xbf" + json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()
        self.set("manifest", "INFO", gzip.compress(raw, 6, mtime=0))

    def write(self, out_path):
        with open(out_path, "wb") as o:
            o.write(b"HDOG" + bytes([self.version]))
            for e in self.entries:
                blob = self.read(e.name)
                e.offset, e.size = o.tell(), len(blob)
                o.write(blob)
            toc = o.tell()
            assert toc < 2**32, "pack too large for u32 offsets"
            for e in self.entries:
                nb = e.name.encode()
                o.write(struct.pack("<II", e.offset, e.size) + _w7(len(nb)) + nb + e.tag.encode())
            o.write(struct.pack("<II", len(self.entries), toc))


if __name__ == "__main__":
    import sys, collections
    h = Hdog(sys.argv[1])
    print("version", h.version, "entries", len(h.entries))
    print(collections.Counter(e.tag for e in h.entries))
    for e in h.entries[:5]:
        print(e)
