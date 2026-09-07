"""Screenshot a Kodi GUI that glReadPixels cannot reach.

Kodi on Amlogic/GBM renders straight to a DRM plane, so its own TakeScreenshot
fails and /dev/fb* holds only the boot splash. The live frame is reachable
through DRM: ask the CRTC which framebuffer it is scanning out, export it as a
dmabuf, and read it.
"""
import ctypes, fcntl, mmap, os, struct, sys, zlib

SCALE = int(os.environ.get("SHOT_SCALE", "2"))
out = sys.argv[1] if len(sys.argv) > 1 else "/storage/shot.png"

def iowr(nr, size):
    return (3 << 30) | (size << 16) | (ord("d") << 8) | nr

GETRESOURCES, GETCRTC, GETFB, PRIME_H2FD = iowr(0xA0, 64), iowr(0xA1, 104), iowr(0xAD, 28), iowr(0x2D, 12)

fd = os.open("/dev/dri/card0", os.O_RDWR)
res = bytearray(64)
fcntl.ioctl(fd, GETRESOURCES, res, True)
ncrtc = struct.unpack_from("<I", res, 36)[0]
buf = mmap.mmap(-1, ncrtc * 4)
addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
struct.pack_into("<QQQQIIII", res, 0, 0, addr, 0, 0, 0, ncrtc, 0, 0)
fcntl.ioctl(fd, GETRESOURCES, res, True)

for crtc_id in struct.unpack_from("<%dI" % ncrtc, buf, 0):
    crtc = bytearray(104)
    struct.pack_into("<QII", crtc, 0, 0, 0, crtc_id)
    try:
        fcntl.ioctl(fd, GETCRTC, crtc, True)
    except OSError:
        continue
    fb_id = struct.unpack_from("<QIIII", crtc)[3]
    if not fb_id:
        continue

    cmd = bytearray(struct.pack("<7I", fb_id, 0, 0, 0, 0, 0, 0))
    fcntl.ioctl(fd, GETFB, cmd, True)
    _fbid, w, h, pitch, _bpp, _depth, handle = struct.unpack("<7I", cmd)
    if not handle:
        continue

    prime = bytearray(struct.pack("<IIi", handle, 0, -1))
    fcntl.ioctl(fd, PRIME_H2FD, prime, True)
    dfd = struct.unpack("<IIi", prime)[2]

    frame = mmap.mmap(dfd, pitch * h, mmap.MAP_SHARED, mmap.PROT_READ)
    ow, oh = w // SCALE, h // SCALE
    rows = []
    for y in range(oh):
        base = y * SCALE * pitch
        line = bytearray(b"\x00")
        for x in range(ow):
            i = base + x * SCALE * 4
            line += bytes((frame[i + 2], frame[i + 1], frame[i]))   # BGRx -> RGB
        rows.append(bytes(line))
    frame.close()

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", ow, oh, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
           + chunk(b"IEND", b""))
    open(out, "wb").write(png)
    print("wrote %s (%dx%d from %dx%d)" % (out, ow, oh, w, h))
    break
else:
    print("no active framebuffer found")
