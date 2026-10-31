#!/usr/bin/env python3
"""Обробка картинки для стилів моушн-графіки, яку не можна зробити CSS (HyperFrames не дозволяє фільтри на відео).

  PY motion/grade.py <стиль> work/<назва>/motion

Бере plate.mp4 (і cutout.webm для collage) з теки й кладе результат туди ж:
  editorial, popart, vhs, terminal → plate.mp4 замінюється обробленою копією (оригінал → plate-original.mp4)
  riso                             → plate.mp4 у дві фарби растром
  collage                          → sticker.webm (людина з білим контуром)
  clean                            → cutout.webm без мерехтіння: меблі, що «блимають» у масці, прибрано, дірки заповнено
Для swiss, glass, doodle, y2k обробка не потрібна (але clean після remove-background — завжди корисно).
"""
import os, shutil, subprocess, sys, tempfile

FILTERS = {
    'editorial': 'eq=saturation=0.82:contrast=1.06:gamma=1.02,colorbalance=rs=0.04:bs=-0.04',
    'popart': 'eq=saturation=1.7:contrast=1.25:brightness=0.02',
    'vhs': 'scale=540:960,scale=1080:1920:flags=bilinear,rgbashift=rh=5:bh=-5,eq=saturation=1.25:contrast=0.92:brightness=0.03,'
           'noise=alls=14:allf=t,gblur=sigma=0.6',
    'terminal': 'eq=brightness=-0.10:saturation=0.45:contrast=1.08,colorbalance=bs=0.10:gs=0.04:rs=-0.06',
}
W, H = 1080, 1920


def run(*a):
    r = subprocess.run([str(x) for x in a], capture_output=True, text=True)
    if r.returncode:
        sys.exit('помилка ffmpeg:\n' + r.stderr[-1200:])


def keep_original(d):
    src, orig = os.path.join(d, 'plate.mp4'), os.path.join(d, 'plate-original.mp4')
    if not os.path.exists(orig):
        shutil.copy(src, orig)
    return orig


def encode(src, vf, out, crf):
    run('ffmpeg', '-v', 'error', '-y', '-i', src, '-vf', vf, '-an', '-c:v', 'libx264', '-preset', 'slow', '-crf', crf, '-g', 30,
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out)


def frames(src, folder, alpha=False):
    os.makedirs(folder, exist_ok=True)
    args = ['ffmpeg', '-v', 'error', '-y']
    if alpha:
        args += ['-c:v', 'libvpx-vp9']   # прозорість у WebM читає лише цей декодер
    run(*args, '-i', src, *(['-vf', 'alphaextract'] if alpha else []), os.path.join(folder, '%04d.png'))
    return sorted(os.path.join(folder, f) for f in os.listdir(folder))


def riso(d, orig):
    import numpy as np
    from PIL import Image
    tmp = tempfile.mkdtemp()
    paper = np.array((245, 239, 226), np.float32)
    pink, blue = np.array((255, 72, 176), np.float32), np.array((0, 120, 191), np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

    def screen(angle, cell=9.0):
        c, s = np.cos(angle), np.sin(angle)
        u, v = (xx * c - yy * s) / cell, (xx * s + yy * c) / cell
        return np.sqrt(((u % 1) - .5) ** 2 + ((v % 1) - .5) ** 2)
    d_pink, d_blue = screen(np.radians(15)), screen(np.radians(75))
    for k, f in enumerate(frames(orig, os.path.join(tmp, 'in'))):
        g = np.asarray(Image.open(f).convert('L').resize((W, H)), np.float32) / 255
        ink_b = np.clip((0.78 - g) * 1.5, 0, 1)
        ink_p = np.clip(1 - np.abs(g - .5) * 2.2, 0, 1) * .85
        dot_b = np.roll((d_blue < np.sqrt(ink_b / np.pi) * .95).astype(np.float32), (3, 4), (0, 1))
        dot_p = (d_pink < np.sqrt(ink_p / np.pi) * .95).astype(np.float32)
        out = paper[None, None] * np.ones((H, W, 1), np.float32)
        out = out * (1 - dot_p[..., None]) + (out * pink / 255) * dot_p[..., None]
        out = out * (1 - dot_b[..., None]) + (out * blue / 255) * dot_b[..., None]
        os.makedirs(os.path.join(tmp, 'out'), exist_ok=True)
        Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(os.path.join(tmp, 'out', '%04d.png' % k))
    run('ffmpeg', '-v', 'error', '-y', '-framerate', 30, '-i', os.path.join(tmp, 'out', '%04d.png'), '-vf', 'gblur=sigma=0.5', '-c:v', 'libx264',
        '-preset', 'slow', '-crf', 18, '-g', 30, '-pix_fmt', 'yuv420p', os.path.join(d, 'plate.mp4'))
    shutil.rmtree(tmp, ignore_errors=True)


def clean(d, orig):
    """Маска без мерехтіння. Впевнена людина лишається як є (навіть руки в русі); сумнівне — не більше медіани ±2 кадри;
    піксель, що збігається з нерухомим фоном плану, — меблі, прибираємо; дірки всередині силуету заповнюємо."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    cut = os.path.join(d, 'cutout.webm')
    if not os.path.exists(cut):
        sys.exit('немає cutout.webm — спершу: npx -y hyperframes remove-background %s -o %s' % (os.path.join(d, 'plate.mp4'), cut))
    tmp = tempfile.mkdtemp()
    rgb, al = frames(orig, os.path.join(tmp, 'rgb')), frames(cut, os.path.join(tmp, 'a'), alpha=True)
    n = min(len(rgb), len(al))
    w, h = W // 2, H // 2   # маску рахуємо на половинному розмірі — у 4 рази швидше, край однаково розмивається
    A = np.stack([np.asarray(Image.open(f).convert('L').resize((w, h)), np.float32) / 255 for f in al[:n]])
    pad = np.concatenate([A[:1], A[:1], A, A[-1:], A[-1:]])
    M = np.where(A > 0.85, A, np.minimum(A, np.median(np.stack([pad[i:i + n] for i in range(5)]), 0)))
    small = np.stack([np.asarray(Image.open(f).convert('L').resize((54, 96)), np.float32) for f in rgb[:n]])
    jumps = np.abs(np.diff(small, axis=0)).mean((1, 2))
    cuts = [0] + [i + 1 for i in np.where(jumps > max(12, jumps.mean() * 6))[0]] + [n]   # склейки між планами
    os.makedirs(os.path.join(tmp, 'out'))
    for a, b in zip(cuts[:-1], cuts[1:]):
        idx = np.linspace(a, b - 1, min(40, b - a)).astype(int)
        fr = np.stack([np.asarray(Image.open(rgb[j]).convert('RGB').resize((w, h)), np.float32) for j in idx])
        seen = np.stack([A[j] for j in idx]) < 0.3
        cnt = seen.sum(0)
        fr[~seen] = np.nan
        with np.errstate(all='ignore'):
            bg = np.nanmedian(fr, 0)
        for k in range(a, b):
            f = np.asarray(Image.open(rgb[k]).convert('RGB').resize((w, h)), np.float32)
            with np.errstate(all='ignore'):
                diff = np.nan_to_num(np.nanmean(np.abs(f - bg), 2), nan=255)
            st = Image.fromarray((((cnt >= 6) & (diff < 16)) * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(5))
            m = M[k] * (1 - np.asarray(st.filter(ImageFilter.GaussianBlur(1.5)), np.float32) / 255)
            t = np.clip((m - 0.5) / 0.3, 0, 1)
            im = Image.fromarray((t * t * (3 - 2 * t) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
            # дірки: заливка фону від країв на зменшеній масці (швидко, без додаткових бібліотек)
            sm = im.resize((w // 4, h // 4)).point(lambda v: 0 if v > 127 else 255).copy()
            for xy in [(x, 0) for x in range(0, w // 4, 4)] + [(x, h // 4 - 1) for x in range(0, w // 4, 4)] + \
                      [(0, y) for y in range(0, h // 4, 4)] + [(w // 4 - 1, y) for y in range(0, h // 4, 4)]:
                if sm.getpixel(xy) == 255:
                    ImageDraw.floodfill(sm, xy, 128)
            holes = sm.point(lambda v: 255 if v == 255 else 0).resize((w, h)).filter(ImageFilter.GaussianBlur(1))
            im = Image.fromarray(np.maximum(np.asarray(im), np.asarray(holes)))
            person = Image.open(rgb[k]).convert('RGBA').resize((W, H))
            person.putalpha(im.resize((W, H), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(1.4)))
            person.save(os.path.join(tmp, 'out', '%04d.png' % k))
    shutil.copy(cut, os.path.join(d, 'cutout-original.webm'))
    run('ffmpeg', '-v', 'error', '-y', '-framerate', 30, '-i', os.path.join(tmp, 'out', '%04d.png'), '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
        '-b:v', 0, '-crf', 26, '-g', 30, '-row-mt', 1, '-auto-alt-ref', 0, cut)
    shutil.rmtree(tmp, ignore_errors=True)


def collage(d, orig):
    from PIL import Image, ImageFilter
    cut = os.path.join(d, 'cutout.webm')
    if not os.path.exists(cut):
        sys.exit('немає cutout.webm — спершу: npx -y hyperframes remove-background %s -o %s' % (os.path.join(d, 'plate.mp4'), cut))
    tmp = tempfile.mkdtemp()
    rgb, alpha = frames(orig, os.path.join(tmp, 'rgb')), frames(cut, os.path.join(tmp, 'a'), alpha=True)
    os.makedirs(os.path.join(tmp, 'out'))
    for k, (f, m) in enumerate(zip(rgb, alpha)):
        a = Image.open(m).convert('L').resize((W, H))
        ring = a.filter(ImageFilter.MaxFilter(29)).filter(ImageFilter.GaussianBlur(1.5))
        im = Image.new('RGBA', (W, H), (255, 255, 255, 0))
        im.putalpha(ring)
        person = Image.open(f).convert('RGBA').resize((W, H))
        person.putalpha(a)
        im.alpha_composite(person)
        im.save(os.path.join(tmp, 'out', '%04d.png' % k))
    run('ffmpeg', '-v', 'error', '-y', '-framerate', 30, '-i', os.path.join(tmp, 'out', '%04d.png'), '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
        '-b:v', 0, '-crf', 28, '-g', 30, '-row-mt', 1, '-auto-alt-ref', 0, os.path.join(d, 'sticker.webm'))
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    style, d = sys.argv[1], sys.argv[2]
    if not os.path.exists(os.path.join(d, 'plate.mp4')):
        sys.exit('у %s немає plate.mp4 — спершу tools/reels.py motion-prep' % d)
    orig = keep_original(d)
    if style in FILTERS:
        encode(orig, FILTERS[style], os.path.join(d, 'plate.mp4'), 26 if style == 'vhs' else 17)
    elif style == 'riso':
        riso(d, orig)
    elif style == 'collage':
        collage(d, orig)
    elif style == 'clean':
        clean(d, orig)
    else:
        print('для стилю %s обробка не потрібна' % style)
        return
    print('готово: %s' % style)


if __name__ == '__main__':
    main()
