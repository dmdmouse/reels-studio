#!/usr/bin/env python3
"""Reels студія: монтаж рілсів кодом. Запускає Claude за скілами з .claude/skills, вручну запускати не обов'язково.

  python tools/reels.py doctor                               перевірити, чи все встановлено
  python tools/reels.py transcribe inbox/a.mov               текст із таймкодами слів → work/<назва>/
  python tools/reels.py plan inbox/a.mov [inbox/b.mov ...]   нарізати на фрази без пауз → work/<назва>/edl.json + plan.md
  python tools/reels.py render work/<назва>/edl.json         склеїти фрази з edl.json → output/<назва>/<назва>-vN.mp4 (1080×1920, −14 LUFS)
  python tools/reels.py tidy <назва> [--keep 3]              лишити в output/<назва>/ лише останні версії, старіші видалити
  python tools/reels.py captions output/x/x-v1.mp4             субтитри: --style pop|plain|box --place bottom|top|center
  python tools/reels.py music output/x.mp4 music/track.mp3   музика під голос (приглушується, коли ти говориш)
  python tools/reels.py insert output/x.mp4 fx.mp4 --at 5    вставити кліп ефекту з 5-ї секунди (звук рілса лишається)
  python tools/reels.py check output/x.mp4                   аркуш із 9 кадрів + тривалість, розмір, гучність
  python tools/reels.py fetch <посилання> [--name назва]     скачати референс (YouTube, TikTok, Instagram) → refs/<назва>.mp4
  python tools/reels.py motion-prep x.mp4 --start 5 --duration 8  шматок рілса для стилю моушн-графіки → work/<назва>/motion/
  python tools/reels.py carousel work/idea.json              карусель 1080×1350 із тексту → output/carousel-<назва>/

Що потрібно: Python 3.9+, ffmpeg з фільтрами ass і loudnorm, для розпізнавання мови — mlx-whisper (Mac M1+) або faster-whisper,
для скачування референсів — yt-dlp.
"""
import argparse, json, os, platform, re, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, FPS = 1080, 1920, 30
# На Mac програми студії лежать у ~/.pixi/bin (скіл studio-setup); повна збірка ffmpeg від Homebrew — окремо від PATH.
for _d in (os.path.expanduser('~/.pixi/bin'), '/opt/homebrew/opt/ffmpeg-full/bin', '/usr/local/opt/ffmpeg-full/bin'):
    if os.path.isdir(_d):
        os.environ['PATH'] = _d + os.pathsep + os.environ.get('PATH', '')
        break
TARGET_LUFS = -14
KEEP_VERSIONS = 3  # скільки останніх версій рілса лишати в його теці


def reel_dir(name):
    """Кожен рілс — своя тека output/<назва>/: усі версії й файли з субтитрами, музикою, ефектами лежать разом."""
    d = os.path.join(ROOT, 'output', name)
    os.makedirs(d, exist_ok=True)
    return d


def versions(name):
    """{номер версії: [файли]} у теці рілса (файл належить версії за «-vN» у назві)."""
    out = {}
    for f in os.listdir(reel_dir(name)):
        m = re.search(r'-v(\d+)(?:\D|$)', f)
        if m and f.endswith('.mp4'):
            out.setdefault(int(m.group(1)), []).append(f)
    return out


def tidy(name, keep=KEEP_VERSIONS):
    """Видаляє версії, старіші за останні keep. Файли з «final» у назві не чіпає ніколи."""
    vs = sorted(versions(name))
    gone = []
    for v in vs[:-keep] if keep > 0 else []:
        for f in versions(name)[v]:
            if 'final' in f.lower():
                continue
            os.remove(os.path.join(reel_dir(name), f))
            gone.append(f)
    if gone:
        print('прибрано старі версії (лишаю останні %d): %s' % (keep, ', '.join(sorted(gone))))
    return gone


def run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        sys.exit('помилка команди: ' + ' '.join(cmd[:4]) + ' …\n' + r.stderr[-1500:])
    return r


def probe(path):
    out = run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,width,height,color_transfer:stream_side_data=rotation',
               '-of', 'json', path]).stdout
    j = json.loads(out)
    v = next((s for s in j['streams'] if s['codec_type'] == 'video'), None)
    has_audio = any(s['codec_type'] == 'audio' for s in j['streams'])
    return {'duration': float(j['format']['duration']), 'video': v, 'audio': has_audio}


def slug(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r'[^\w-]+', '-', name, flags=re.U).strip('-').lower() or 'video'


def workdir(name):
    d = os.path.join(ROOT, 'work', name)
    os.makedirs(d, exist_ok=True)
    return d


def ts(sec):
    return '%02d:%04.1f' % (int(sec // 60), sec % 60)


# ---------- перевірка ----------

def whisper_engine():
    try:
        import mlx_whisper  # noqa: F401
        return 'mlx-whisper'
    except Exception:
        pass
    try:
        import faster_whisper  # noqa: F401
        return 'faster-whisper'
    except Exception:
        return None


def cmd_doctor(a):
    ok = True
    def line(good, text, fix=''):
        nonlocal ok
        ok = ok and good
        print(('✅ ' if good else '❌ ') + text + ('' if good or not fix else '\n   → ' + fix))
    line(sys.version_info >= (3, 9), 'Python %d.%d' % sys.version_info[:2], 'потрібен Python 3.9 або новіший')
    ff = shutil.which('ffmpeg') and shutil.which('ffprobe')
    line(bool(ff), 'ffmpeg і ffprobe', 'Mac: скіл studio-setup, розділ «Програми» · Windows: winget install Gyan.FFmpeg')
    if ff:
        filters = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True).stdout
        for f, why in (('ass', 'субтитри'), ('loudnorm', 'гучність')):
            line(re.search(r'\s%s\s' % f, filters) is not None, 'ffmpeg вміє %s (%s)' % (f, why),
                 'Mac: перевстанови ffmpeg за скілом studio-setup')
    eng = whisper_engine()
    mac_arm = platform.system() == 'Darwin' and platform.machine() == 'arm64'
    line(eng is not None, 'розпізнавання мови: %s' % (eng or 'не встановлено'),
         'pip install %s у .venv цієї папки' % ('mlx-whisper' if mac_arm else 'faster-whisper'))
    try:
        import yt_dlp  # noqa: F401
        has_ytdlp = True
    except Exception:
        has_ytdlp = False
    line(has_ytdlp, 'yt-dlp (скачування референсів за посиланням)', 'pip install yt-dlp у .venv цієї папки')
    for d in ('inbox', 'output', 'work', 'music', 'refs'):
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)
    print('\nВСЕ ГОТОВО ✅' if ok else '\nЄ що виправити ❌ — виправ перший червоний пункт і запусти doctor ще раз.')
    sys.exit(0 if ok else 1)


# ---------- розпізнавання ----------

DEFAULT_PROMPT = 'Claude, Reels, AI'


def profile_words():
    """Слова з CLAUDE.md («Слова, які Whisper пише неправильно: …») — щоб їх не треба було щоразу передавати в --prompt."""
    try:
        text = open(os.path.join(ROOT, 'CLAUDE.md'), encoding='utf-8').read()
    except OSError:
        return ''
    m = re.search(r'Слова, які Whisper пише неправильно:\s*(.+)', text)
    words = m.group(1).strip() if m else ''
    return '' if not words or words.startswith('[') else words.strip('[]')
# Як Whisper зазвичай чує назви по-українському — виправляємо завжди, без окремого fixes.json.
DEFAULT_FIXES = {'клода': 'Claude', 'клод': 'Claude', 'клоду': 'Claude', 'клодом': 'Claude', 'клоді': 'Claude',
                 'клауд': 'Claude', 'клауде': 'Claude', 'рілз': 'Reels', 'рілзи': 'Reels'}


def transcribe(src, lang='uk', prompt=None):
    """Повертає список слів [{'t','s','e'}] і кешує в work/<назва>/words.json."""
    prompt = ', '.join(x for x in (prompt or DEFAULT_PROMPT, profile_words()) if x)
    d = workdir(slug(src))
    cache = os.path.join(d, 'words.json')
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(src):
        return json.load(open(cache, encoding='utf-8'))
    wav = os.path.join(d, 'voice16k.wav')
    run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-vn', '-ac', '1', '-ar', '16000', wav])
    eng = whisper_engine()
    words = []
    if eng == 'mlx-whisper':
        import mlx_whisper
        res = mlx_whisper.transcribe(wav, path_or_hf_repo=os.getenv('REELS_WHISPER', 'mlx-community/whisper-large-v3-turbo'),
                                     word_timestamps=True, language=lang, initial_prompt=prompt)
        for s in res['segments']:
            words += [{'t': w['word'].strip(), 's': round(w['start'], 3), 'e': round(w['end'], 3)} for w in s.get('words', [])]
    elif eng == 'faster-whisper':
        from faster_whisper import WhisperModel
        model = WhisperModel(os.getenv('REELS_WHISPER', 'large-v3-turbo'), device='auto', compute_type='int8')
        segs, _ = model.transcribe(wav, language=lang, word_timestamps=True, initial_prompt=prompt, vad_filter=True)
        for s in segs:
            words += [{'t': w.word.strip(), 's': round(w.start, 3), 'e': round(w.end, 3)} for w in (s.words or [])]
    else:
        sys.exit('розпізнавання мови не встановлене: запусти doctor')
    words = [w for w in words if w['t']]
    json.dump(words, open(cache, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    return words


def phrases(words, gap):
    out, cur = [], []
    for w in words:
        if cur and (w['s'] - cur[-1]['e'] > gap):
            out.append(cur); cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def cmd_transcribe(a):
    words = transcribe(a.video, a.lang, a.prompt)
    d = workdir(slug(a.video))
    with open(os.path.join(d, 'transcript.txt'), 'w', encoding='utf-8') as f:
        for p in phrases(words, 0.6):
            f.write('[%s–%s] %s\n' % (ts(p[0]['s']), ts(p[-1]['e']), ' '.join(w['t'] for w in p)))
    print(open(os.path.join(d, 'transcript.txt'), encoding='utf-8').read())
    print('збережено: work/%s/transcript.txt і words.json' % slug(a.video))


# ---------- нарізка ----------

def cmd_plan(a):
    clips = []
    for src in a.videos:
        info = probe(src)
        if not info['audio']:
            sys.exit('%s: немає звуку — нічого розпізнати' % src)
        tr = (info['video'] or {}).get('color_transfer')
        if tr in ('arib-std-b67', 'smpte2084'):
            print('⚠️  %s знято в HDR: кольори можуть бути блідими. На наступну зйомку вимкни HDR-відео в налаштуваннях камери.' % src)
        words = transcribe(src, a.lang, a.prompt)
        for p in phrases(words, a.gap):
            start = max(0.0, p[0]['s'] - a.pad)
            end = min(info['duration'], p[-1]['e'] + a.pad + 0.08)
            clips.append({'src': os.path.relpath(src, ROOT), 'start': round(start, 3), 'end': round(end, 3),
                          'text': ' '.join(w['t'] for w in p)})
    name = a.name or slug(a.videos[0])
    d = workdir(name)
    edl = {'name': name, 'clips': clips}
    path = os.path.join(d, 'edl.json')
    json.dump(edl, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    with open(os.path.join(d, 'plan.md'), 'w', encoding='utf-8') as f:
        f.write('# План нарізки: %s\n\nКожен рядок — фраза без пауз. Дублі та зайве видаляй з edl.json (або попроси Claude).\n\n' % name)
        for i, c in enumerate(clips, 1):
            f.write('%d. %s [%s–%s] %s\n' % (i, os.path.basename(c['src']), ts(c['start']), ts(c['end']), c['text']))
    print(open(os.path.join(d, 'plan.md'), encoding='utf-8').read())
    total = sum(c['end'] - c['start'] for c in clips)
    print('фраз: %d · після нарізки ≈ %.1f с · edl: work/%s/edl.json' % (len(clips), total, name))


VERTICAL = 'scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d' % (W, H, W, H, FPS)


def vertical(x=None):
    """Вертикальний кадр. x — де людина в горизонтальному відео: 0 ліворуч, 0.5 центр, 1 праворуч."""
    if x is None:
        return VERTICAL
    return 'scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d:(iw-%d)*%.3f:(ih-%d)/2,setsar=1,fps=%d' % (W, H, W, H, W, float(x), H, FPS)


def loudnorm_args():
    return ['-af', 'loudnorm=I=%d:TP=-1.5:LRA=11' % TARGET_LUFS, '-ar', '48000', '-c:a', 'aac', '-b:a', '192k']


def cmd_render(a):
    edl = json.load(open(a.edl, encoding='utf-8'))
    clips = edl['clips']
    if not clips:
        sys.exit('edl.json порожній')
    d = workdir(edl.get('name', 'video'))
    parts = []
    for i, c in enumerate(clips):
        part = os.path.join(d, 'part%03d.mp4' % i)
        run(['ffmpeg', '-v', 'error', '-y', '-ss', str(c['start']), '-to', str(c['end']), '-i', os.path.join(ROOT, c['src']),
             '-vf', 'fps=%d,scale=trunc(iw/2)*2:trunc(ih/2)*2' % FPS if edl.get('raw') else vertical(c.get('x', edl.get('x'))),   # raw: запис екрана без вертикального кадру
             '-g', '30', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-b:a', '192k', part])
        parts.append(part)
    lst = os.path.join(d, 'parts.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        f.writelines("file '%s'\n" % os.path.basename(p) for p in parts)
    joined = os.path.join(d, 'joined.mp4')
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', 'parts.txt', '-c', 'copy', 'joined.mp4'], cwd=d)
    name = re.sub(r'-v\d+$', '', edl.get('name', 'video'))
    out = a.out or os.path.join(reel_dir(name), '%s-v%d.mp4' % (name, max(versions(name), default=0) + 1))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    run(['ffmpeg', '-v', 'error', '-y', '-i', joined, '-c:v', 'copy'] + loudnorm_args() + ['-movflags', '+faststart', out])
    print('готово: %s · %.1f с' % (os.path.relpath(out, ROOT), probe(out)['duration']))
    if not a.out:
        tidy(name)


# ---------- субтитри ----------

STOP = set('я ти ми ви він вона вони в у з із і й та а але що як не ні про для на до від по за це той ця ці там тут так бо ж же чи коли який яка які щоб'.split())
STYLES = {
    # назва: шрифт, розмір, ВЕЛИКІ, контур, тінь, тип рамки (1 контур, 3 плашка), макс. символів у рядку
    'pop':   ('Arial Black', 88, True, 7, 0, 1, 16),
    'plain': ('Arial', 66, False, 5, 0, 1, 26),
    'box':   ('Arial', 62, False, 14, 0, 3, 24),
}


def chunks(words, max_chars):
    out, cur = [], []
    for w in words:
        text = ' '.join(x['t'] for x in cur + [w])
        if cur and (len(text) > max_chars or w['s'] - cur[-1]['e'] > 0.5 or (len(cur) >= 3)):
            out.append(cur); cur = []
        cur.append(w)
        if re.search(r'[.!?…,:;]$', w['t']) and w['t'].lower().strip('.,!?…:;') not in STOP:
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    # службове слово в кінці фрази переносимо до наступної
    for i in range(len(out) - 1):
        if len(out[i]) > 1 and out[i][-1]['t'].lower() in STOP:
            out[i + 1].insert(0, out[i].pop())
    return [c for c in out if c]


def ass_time(t):
    t = max(0, t)
    return '%d:%02d:%05.2f' % (int(t // 3600), int(t % 3600 // 60), t % 60)


def cmd_captions(a):
    words = transcribe(a.video, a.lang, a.prompt)
    fixes = dict(DEFAULT_FIXES, **(json.load(open(a.fixes, encoding='utf-8')) if a.fixes else {}))
    for w in words:
        key = w['t'].strip('.,!?…:;«»"').lower()
        for wrong, right in fixes.items():
            if key == wrong.lower():
                w['t'] = w['t'].replace(w['t'].strip('.,!?…:;«»"'), right)
    font, size, caps, outline, shadow, border, max_chars = STYLES[a.style]
    align, margin = {'bottom': (2, int(H * 0.27)), 'top': (8, int(H * 0.17)), 'center': (5, 0)}[a.place]
    back = '&H99000000' if border == 3 else '&H00000000'
    lines = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: %d' % W, 'PlayResY: %d' % H, 'WrapStyle: 0', '',
             '[V4+ Styles]',
             'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
             'Style: Main,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,%s,-1,0,0,0,100,100,0,0,%d,%d,%d,%d,90,90,%d,1' % (font, size, back, border, outline, shadow, align, margin),
             'Style: Title,Arial Black,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,8,0,8,90,90,%d,1' % int(H * 0.14),
             '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    if a.title:  # заголовок-хук угорі на перші секунди
        lines.append('Dialogue: 1,0:00:00.00,%s,Title,,0,0,0,,{\\fad(0,250)}%s' % (ass_time(a.title_seconds), a.title.upper().replace('|', '\\N')))
    highlight = '{\\c&H' + a.color + '&}'
    skip = [tuple(map(float, r.split('-'))) for r in a.skip.split(',')] if a.skip else []   # секунди без субтитрів: там вставка зі своїм текстом
    cs = [c for c in chunks(words, max_chars) if not any(c[0]['s'] < y and c[-1]['e'] > x for x, y in skip)]
    for i, c in enumerate(cs):
        end_chunk = cs[i + 1][0]['s'] if i + 1 < len(cs) and cs[i + 1][0]['s'] - c[-1]['e'] < 0.4 else c[-1]['e'] + 0.25
        for j, w in enumerate(c):
            s = w['s'] if j else c[0]['s']
            e = c[j + 1]['s'] if j + 1 < len(c) else end_chunk
            text = []
            for k, x in enumerate(c):
                t = x['t'].upper() if caps else x['t']
                t = re.sub(r'[,.;:…]+$', '', t).replace('{', '(').replace('}', ')')  # кома й крапка в кінці на екрані зайві
                text.append(highlight + t + '{\\c&HFFFFFF&}' if (a.style == 'pop' and k == j) else t)
            pop = '{\\fscx85\\fscy85\\t(0,90,\\fscx100\\fscy100)}' if (a.style == 'pop' and j == 0) else ''
            lines.append('Dialogue: 0,%s,%s,Main,,0,0,0,,%s%s' % (ass_time(s), ass_time(e), pop, ' '.join(text)))
    name = slug(a.video)
    d = workdir(name)
    with open(os.path.join(d, 'captions.ass'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    out = os.path.abspath(a.out or os.path.join(os.path.dirname(os.path.abspath(a.video)), name + '-subs.mp4'))  # поруч із відео, у теці рілса
    run(['ffmpeg', '-v', 'error', '-y', '-i', os.path.abspath(a.video), '-vf', 'ass=captions.ass', '-c:v', 'libx264', '-preset', 'medium',
         '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart', out], cwd=d)
    print('субтитри (%s, %s): %s · фраз на екрані: %d · текст для перевірки: work/%s/captions.ass' %
          (a.style, a.place, os.path.relpath(out, ROOT), len(cs), name))


# ---------- музика ----------

def cmd_music(a):
    out = a.out or os.path.splitext(a.video)[0] + '-music.mp4'
    dur = probe(a.video)['duration']
    fade = max(0.0, dur - 1.5)
    # музика тихіше голосу на ~18 dB і ще приглушується (sidechain), коли звучить голос
    graph = ('[1:a]aloop=loop=-1:size=2e9,atrim=0:%.2f,volume=%sdB,afade=t=out:st=%.2f:d=1.5[m];'
             '[m][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];'
             '[0:a][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=%d:TP=-1.5:LRA=11[a]') % (dur, a.level, fade, TARGET_LUFS)
    run(['ffmpeg', '-v', 'error', '-y', '-i', a.video, '-i', a.track, '-filter_complex', graph, '-map', '0:v', '-map', '[a]',
         '-c:v', 'copy', '-c:a', 'aac', '-ar', '48000', '-b:a', '192k', '-movflags', '+faststart', out])
    print('з музикою: %s' % out)


# ---------- вставка ефекту ----------

def cmd_insert(a):
    """Ставить кліп ефекту поверх рілса з секунди --at; голос рілса лишається. --sound додає звуки самого кліпу."""
    out = a.out or os.path.splitext(a.video)[0] + '-fx.mp4'
    dur = probe(a.clip)['duration']
    at = float(a.at)
    graph = ('[1:v]%s,setpts=PTS-STARTPTS+%.3f/TB[fx];'
             '[0:v][fx]overlay=enable=\'between(t,%.3f,%.3f)\':eof_action=pass[v]') % (VERTICAL, at, at, at + dur)
    audio = ['-map', '0:a?', '-c:a', 'copy']
    if a.sound and probe(a.clip)['audio']:
        graph += ';[1:a]adelay=%d:all=1[fxa];[0:a][fxa]amix=inputs=2:normalize=0:duration=first,loudnorm=I=%d:TP=-1.5:LRA=11[a]' % (round(at * 1000), TARGET_LUFS)
        audio = ['-map', '[a]', '-ar', '48000', '-c:a', 'aac', '-b:a', '192k']
    run(['ffmpeg', '-v', 'error', '-y', '-i', a.video, '-i', a.clip, '-filter_complex', graph, '-map', '[v]', *audio,
         '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out])
    print('ефект вставлено з %s по %s: %s' % (ts(at), ts(at + dur), out))


# ---------- перевірка результату ----------

def cmd_check(a):
    info = probe(a.video)
    v = info['video'] or {}
    d = workdir(slug(a.video))
    sheet = os.path.join(d, 'sheet.jpg')
    n, dur = 9, info['duration']
    step = dur / (n + 1)
    run(['ffmpeg', '-v', 'error', '-y', '-i', a.video, '-vf', 'fps=1/%.3f,scale=360:-2,tile=3x3:padding=6:color=white' % step,
         '-frames:v', '1', sheet])
    lufs = None
    if info['audio']:
        r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', a.video, '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True)
        m = re.findall(r'I:\s+(-?[\d.]+) LUFS', r.stderr)
        lufs = float(m[-1]) if m else None
    warn = []
    if (v.get('width'), v.get('height')) != (W, H):
        warn.append('розмір %sx%s, а треба %dx%d' % (v.get('width'), v.get('height'), W, H))
    if lufs is None:
        warn.append('немає звуку')
    elif not -16 <= lufs <= -12:
        warn.append('гучність %.1f LUFS, а треба близько %d' % (lufs, TARGET_LUFS))
    if dur > 90:
        warn.append('довше 90 с — для рілса задовго')
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', a.video, '-vf', 'freezedetect=n=-60dB:d=1.5', '-map', '0:v', '-f', 'null', '-'], capture_output=True, text=True)
    for st, fd in zip(re.findall(r'freeze_start: ([\d.]+)', r.stderr), re.findall(r'freeze_duration: ([\d.]+)', r.stderr)):
        warn.append('картинка стоїть %s с на %s — це навмисно?' % (fd[:4], ts(float(st))))
    print('файл: %s\nтривалість: %.1f с · розмір: %sx%s · гучність: %s' % (a.video, dur, v.get('width'), v.get('height'),
          ('%.1f LUFS' % lufs) if lufs is not None else '—'))
    print('аркуш кадрів: %s' % os.path.relpath(sheet, ROOT))
    if a.listen and info['audio']:
        words = transcribe(a.video, a.lang, a.prompt)
        clean = [re.sub(r'[^\w\']', '', w['t'].lower()) for w in words]
        print('що чути в готовому відео:\n' + ' '.join(w['t'] for w in words))
        for n in (3, 2, 1):
            for i in range(len(clean) - 2 * n + 1):
                if clean[i:i + n] == clean[i + n:i + 2 * n] and all(len(c) > 2 or n > 1 for c in clean[i:i + n]):
                    warn.append('повтор «%s» на %s — дубль лишився?' % (' '.join(clean[i:i + n]), ts(words[i]['s'])))
    print('⚠️  ' + '\n⚠️  '.join(warn) if warn else '✅ технічно все гаразд — тепер подивись аркуш: текст не обрізаний, не на обличчі, читається')


# ---------- карусель ----------

# фон, акцент, текст
PALETTES = {
    'light': ('#FFFFFF', '#FF4A1C', '#0E0E0F'), 'dark': ('#0E0E0F', '#FF4A1C', '#FFFFFF'),
    'horizon': ('#172b39', '#ff9b4f', '#f4e9d5'), 'paper': ('#ede7d9', '#4b5b49', '#1b2620'),
    'poster': ('#f15c36', '#ffcf73', '#1b1919'), 'classic': ('#e5ddcb', '#6d765b', '#2b3326'),
    'soft': ('#eadbd7', '#a06577', '#36282e'), 'pop': ('#e658a0', '#ffe34a', '#28202a'),
    'agency': ('#121418', '#a9fc4e', '#f5f5ed'), 'creator': ('#18291e', '#efc56e', '#fff6df'),
}


def wrap(draw, text, font, width):
    lines = []
    for para in text.split('\n'):
        cur = ''
        for word in para.split():
            test = (cur + ' ' + word).strip()
            if draw.textlength(test, font=font) <= width or not cur:
                cur = test
            else:
                lines.append(cur); cur = word
        lines.append(cur)
    return lines


def cmd_carousel(a):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        sys.exit('потрібен Pillow: pip install pillow у .venv цієї папки')
    spec = json.load(open(a.slides, encoding='utf-8'))
    bg, accent, ink = PALETTES[spec.get('palette', 'light')]
    fonts = os.path.join(ROOT, 'fonts')
    f = lambda size, bold=True: ImageFont.truetype(os.path.join(fonts, 'manrope-800.ttf' if bold else 'manrope-600.ttf'), size)
    slides = spec['slides']
    out = os.path.join(ROOT, 'output', 'carousel-' + slug(a.slides))
    os.makedirs(out, exist_ok=True)
    CW, CH, M = 1080, 1350, 96
    for i, s in enumerate(slides, 1):
        if spec.get('palette', 'light') == 'light':  # світлі слайди, останній із закликом — темний
            bg, accent, ink = PALETTES['dark' if i == len(slides) else 'light']
        im = Image.new('RGB', (CW, CH), bg)
        d = ImageDraw.Draw(im)
        d.text((M, M), '%02d / %02d' % (i, len(slides)), font=f(30, False), fill=accent)
        y = M + 120
        size = 104 if i == 1 else 72
        title = s.get('title', '')
        while size > 40 and len(wrap(d, title, f(size), CW - 2 * M)) > (6 if i == 1 else 4):
            size -= 6
        for line in wrap(d, title, f(size), CW - 2 * M):
            d.text((M, y), line, font=f(size), fill=ink)
            y += int(size * 1.12)
        if s.get('text'):
            y += 40
            d.rectangle((M, y, M + 90, y + 8), fill=accent)
            y += 50
            for line in wrap(d, s['text'], f(44, False), CW - 2 * M):
                d.text((M, y), line, font=f(44, False), fill=ink)
                y += 62
        if y > CH - M - 60:
            print('⚠️  слайд %d: забагато тексту, скороти' % i)
        d.text((M, CH - M - 30), spec.get('handle', ''), font=f(30, False), fill=ink)
        if i < len(slides):
            d.text((CW - M - 60, CH - M - 34), '→', font=f(40), fill=accent)
        im.save(os.path.join(out, '%02d.png' % i))
    print('карусель: %s · слайдів: %d' % (os.path.relpath(out, ROOT), len(slides)))


def cmd_motion_prep(a):
    """Шматок рілса для HyperFrames: plate.mp4 (без звуку, 1080×1920, 30 к/с, ключовий кадр щосекунди — щоб точно перемотувалось),
    voice.m4a і words.json у форматі HyperFrames ({id, text, start, end} від початку шматка)."""
    name = a.name or slug(a.video)
    d = os.path.join(workdir(name), 'motion')
    os.makedirs(d, exist_ok=True)
    start, dur = float(a.start), float(a.duration)
    run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(dur), '-i', a.video, '-vf', VERTICAL, '-an', '-c:v', 'libx264',
         '-preset', 'medium', '-crf', '16', '-g', str(FPS), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', os.path.join(d, 'plate.mp4')])
    run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(dur), '-i', a.video, '-vn', '-c:a', 'aac', '-b:a', '192k',
         os.path.join(d, 'voice.m4a')])
    words = [w for w in transcribe(a.video, a.lang, a.prompt) if start - 0.05 <= w['s'] < start + dur - 0.1]
    out = [{'id': 'w%d' % i, 'text': w['t'], 'start': round(max(0, w['s'] - start), 2), 'end': round(min(w['e'], start + dur) - start, 2)}
           for i, w in enumerate(words)]
    with open(os.path.join(d, 'words.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('шматок для моушн-графіки: %s · %.1f с · слів: %d\n%s' % (os.path.relpath(d, ROOT), dur, len(out), ' '.join(w['text'] for w in out)))
    print('далі — людина без фону: npx -y hyperframes remove-background %s -o %s' %
          (os.path.relpath(os.path.join(d, 'plate.mp4'), ROOT), os.path.relpath(os.path.join(d, 'cutout.webm'), ROOT)))


def cmd_tidy(a):
    if not tidy(a.name, a.keep):
        print('нічого прибирати: в output/%s/ не більше %d версій' % (a.name, a.keep))


def cmd_fetch(a):
    """Референс за посиланням → refs/<назва>.mp4 (до 1080p, mp4)."""
    try:
        import yt_dlp
    except ImportError:
        sys.exit('yt-dlp не встановлено: .venv/bin/python -m pip install yt-dlp (Windows: .venv\\Scripts\\python -m pip install yt-dlp)')
    refs = os.path.join(ROOT, 'refs')
    os.makedirs(refs, exist_ok=True)
    name = a.name or 'ref-%s' % re.sub(r'\W+', '-', a.url.rstrip('/').split('/')[-1].split('?')[0])[:40].strip('-').lower()
    out = os.path.join(refs, name + '.mp4')
    if os.path.exists(out):
        sys.exit('%s уже є — дай іншу назву через --name' % os.path.relpath(out, ROOT))
    opts = {'outtmpl': os.path.join(refs, name + '.%(ext)s'), 'format': 'bv*[height<=1920][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b',
            'merge_output_format': 'mp4', 'noplaylist': True, 'quiet': True, 'no_warnings': True, 'noprogress': True}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([a.url])
    except Exception as e:
        sys.exit('не вдалося скачати: %s\nInstagram інколи вимагає входу — тоді збережи відео з телефона й поклади в refs/.' % str(e)[-300:])
    info = probe(out)
    print('референс: %s · %.1f с · %sx%s' % (os.path.relpath(out, ROOT), info['duration'], info['video']['width'], info['video']['height']))


def main():
    p = argparse.ArgumentParser(description='Reels студія: монтаж рілсів кодом')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('doctor').set_defaults(f=cmd_doctor)
    for name, f in (('transcribe', cmd_transcribe), ('captions', cmd_captions)):
        s = sub.add_parser(name); s.add_argument('video'); s.set_defaults(f=f)
        s.add_argument('--lang', default='uk'); s.add_argument('--prompt', help='слова, які треба впізнати правильно: "Claude, Reels"')
    s = sub.choices['captions']
    s.add_argument('--skip', help='секунди без субтитрів: 7.3-10.5,23.5-28.3')
    s.add_argument('--style', choices=list(STYLES), default='pop'); s.add_argument('--place', choices=['bottom', 'top', 'center'], default='bottom')
    s.add_argument('--color', default='00E5FF', help='колір активного слова у форматі BBGGRR (00E5FF — жовтий)')
    s.add_argument('--fixes', help='json виправлень: {"клод": "Claude"}'); s.add_argument('--out')
    s.add_argument('--title', help='заголовок-хук угорі; | — новий рядок'); s.add_argument('--title-seconds', type=float, default=2.5)
    s = sub.add_parser('plan'); s.add_argument('videos', nargs='+'); s.add_argument('--name'); s.add_argument('--gap', type=float, default=0.45)
    s.add_argument('--pad', type=float, default=0.10); s.add_argument('--lang', default='uk'); s.add_argument('--prompt'); s.set_defaults(f=cmd_plan)
    s = sub.add_parser('render'); s.add_argument('edl'); s.add_argument('--out'); s.set_defaults(f=cmd_render)
    s = sub.add_parser('music'); s.add_argument('video'); s.add_argument('track'); s.add_argument('--level', default='-18'); s.add_argument('--out'); s.set_defaults(f=cmd_music)
    s = sub.add_parser('check'); s.add_argument('video'); s.add_argument('--listen', action='store_true', help='ще раз розпізнати голос у готовому відео')
    s.add_argument('--lang', default='uk'); s.add_argument('--prompt'); s.set_defaults(f=cmd_check)
    s = sub.add_parser('motion-prep'); s.add_argument('video'); s.add_argument('--start', required=True); s.add_argument('--duration', default='8')
    s.add_argument('--name'); s.add_argument('--lang', default='uk'); s.add_argument('--prompt'); s.set_defaults(f=cmd_motion_prep)
    s = sub.add_parser('tidy'); s.add_argument('name'); s.add_argument('--keep', type=int, default=KEEP_VERSIONS); s.set_defaults(f=cmd_tidy)
    s = sub.add_parser('fetch'); s.add_argument('url'); s.add_argument('--name'); s.set_defaults(f=cmd_fetch)
    s = sub.add_parser('insert'); s.add_argument('video'); s.add_argument('clip'); s.add_argument('--at', required=True, help='секунда рілса'); s.add_argument('--sound', action='store_true', help='додати звуки кліпу до голосу')
    s.add_argument('--out'); s.set_defaults(f=cmd_insert)
    s = sub.add_parser('carousel'); s.add_argument('slides', help='json: {"palette":"light","handle":"@нік","slides":[{"title":"…","text":"…"}]}')
    s.set_defaults(f=cmd_carousel)
    a = p.parse_args()
    a.f(a)


if __name__ == '__main__':
    main()
