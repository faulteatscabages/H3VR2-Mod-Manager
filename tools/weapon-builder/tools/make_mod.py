"""Pack a hand-written mod folder (mod.json [+ icon.png] [+ bundles/]) into a .h3mod.

  python make_mod.py <mod folder> <dest dir>

If there is no icon.png, a simple title card is drawn from the mod's name.
"""
import io, json, os, sys, zipfile
from PIL import Image, ImageDraw, ImageFont


def card(title, kind):
    im = Image.new("RGBA", (512, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, 504, 248), 28, fill=(40, 44, 58, 255), outline=(120, 170, 230, 255), width=6)
    try:
        f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 54)
        g = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 34)
    except OSError:
        f = g = ImageFont.load_default()
    d.text((256, 110), title.split(" (")[0], font=f, fill=(255, 255, 255, 255), anchor="mm")
    d.text((256, 180), kind.upper(), font=g, fill=(150, 190, 240, 255), anchor="mm")
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


def main(src, dest):
    meta = json.load(open(os.path.join(src, "mod.json")))
    os.makedirs(dest, exist_ok=True)
    out = os.path.join(dest, meta["id"] + ".h3mod")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mod.json", json.dumps(meta, separators=(",", ":")))
        icon = os.path.join(src, "icon.png")
        z.writestr("icon.png", open(icon, "rb").read() if os.path.exists(icon) else card(meta["name"], meta.get("kind", "mod")))
        bd = os.path.join(src, "bundles")
        if os.path.isdir(bd):
            for n in os.listdir(bd):
                z.write(os.path.join(bd, n), "bundles/" + n, compress_type=zipfile.ZIP_STORED)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
