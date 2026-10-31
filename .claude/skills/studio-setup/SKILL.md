---
name: studio-setup
description: Перше налаштування Reels студії — перевірити комп'ютер, встановити ffmpeg, Python-середовище й розпізнавання мови. Використовуй, коли людина просить «налаштуй студію», «встанови все», «не працює doctor», або коли tools/reels.py doctor показує ❌.
---

# Налаштування студії

Людина — новачок. Пояснюй кожен крок одним реченням, без жаргону. Встановлюй лише безкоштовне. Паролі людина вводить сама — ти їх не просиш і не вводиш.

## 1. Визнач систему
Запусти `uname -s` (Mac/Linux) або перевір, чи це Windows. Для Mac — ще `uname -m` (arm64 = Apple Silicon M1+).

## 2. Програми
**Mac** (Homebrew, Термінал і пароль не потрібні: усе ляже в теку `~/.pixi` у домашній папці)
1. Завантаж pixi, маленьку програму, яка поставить решту:
```
mkdir -p ~/.pixi/bin && curl -fsSL "https://github.com/prefix-dev/pixi/releases/latest/download/pixi-$(uname -m | sed s/arm64/aarch64/)-apple-darwin.tar.gz" | tar xz -C ~/.pixi/bin
```
2. `~/.pixi/bin/pixi global install ffmpeg python=3.12` (близько 600 МБ).
3. Щоб наступні сесії бачили ці програми: `grep -q '.pixi/bin' ~/.zshrc 2>/dev/null || echo 'export PATH="$HOME/.pixi/bin:$PATH"' >> ~/.zshrc`

**Windows**
1. `winget install -e --id Python.Python.3.12` і `winget install -e --id Gyan.FFmpeg`
2. Попроси людину закрити й знову відкрити Claude, щоб нові програми стали видимі.

## 3. Python-середовище в цій папці
Mac (Apple Silicon), **не бери `python3`**: на Mac це зазвичай старий Python 3.9 від Apple.
```
~/.pixi/bin/python -m venv .venv
.venv/bin/python -m pip install -U pip mlx-whisper pillow yt-dlp
```
Mac Intel / Linux: те саме, але замість `mlx-whisper` — `faster-whisper`.
Жовті попередження pip («Cache entry deserialization failed» тощо) нешкідливі — скажи людині, що на них можна не зважати.
Windows:
```
py -3 -m venv .venv
.venv\Scripts\python -m pip install -U pip faster-whisper pillow yt-dlp
```
Далі в усіх скілах `PY` = `.venv/bin/python` (Mac) або `.venv\Scripts\python` (Windows).

## 4. Перевірка
`PY tools/reels.py doctor` — має бути «ВСЕ ГОТОВО ✅». Червоний пункт — виправ саме його й запусти doctor знову. Не переходь далі, поки є ❌.

## 5. Модель розпізнавання мови
Завантаж її зараз, щоб пізніше не чекати. Скажи людині, що це один раз: близько 1,5 ГБ, кілька хвилин.
```
ffmpeg -v error -y -f lavfi -i "anoisesrc=d=2:c=pink:a=0.002" -ar 16000 -ac 1 work/model-check.wav
PY tools/reels.py transcribe work/model-check.wav
```
Це двосекундний тихий шум: дивний текст у результаті нормальний, важливо лише, що команда завершилась без помилки. Потім видали `work/model-check.wav` і теку `work/model-check/`.

## 6. Підсумок для людини
Три рядки: що встановлено, що студія готова, наступний крок — дві проби з кроку 8 уроку Дня 1.

## Моушн-графіка (один раз, коли знадобиться вперше)
Стилі моушн-графіки (скіл motion-styles) працюють на HyperFrames — безкоштовній відкритій програмі, яка рендерить HTML у відео. Їй потрібен Node.js 22+.
1. Mac: `PATH="$HOME/.pixi/bin:$PATH" node -v`, Windows: `node -v`. Є 22 або новіше — переходь до кроку 3.
2. Mac: `~/.pixi/bin/pixi global install nodejs=22`, а в цій сесії перед кожною командою `npx` додавай `export PATH="$HOME/.pixi/bin:$PATH" &&`. Windows: `winget install -e --id OpenJS.NodeJS.LTS`, потім попроси людину закрити й знову відкрити Claude.
3. Вимкни статистику HyperFrames і перевір: Mac `export PATH="$HOME/.pixi/bin:$PATH" HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1 && npx -y hyperframes@latest doctor` (Windows: `set HYPERFRAMES_NO_TELEMETRY=1` і та сама команда). Перший запуск завантажує програму й браузер для рендеру — кілька хвилин.
4. Правила HyperFrames для Claude — у цій теці: `npx -y hyperframes@latest skills update`.
5. Скажи людині одним рядком: «Моушн-графіка готова. Спробуй: зроби шматок мого рілса у стилі Swiss за скілом motion-styles».

## Remotion (один раз, коли знадобиться вперше)
Remotion — другий рушій для відео з коду, на React. Йому теж потрібен Node.js 22+ (кроки 1–2 розділу «Моушн-графіка»). На Mac перед кожною командою `npx` і `npm` додавай `export PATH="$HOME/.pixi/bin:$PATH" &&`.
1. Створи окремий проєкт у теці студії: `npx -y create-video@latest --yes --blank remotion-studio`
2. Постав правила Remotion для Claude: `cd remotion-studio && npx -y remotion skills add`. Прочитай їх перед першою сценою.
3. Сцени пиши в `remotion-studio/src/`, рендер: `npx remotion render <назва композиції> ../output/<назва>/<файл>.mp4`.
4. Скажи людині одним рядком: «Remotion готовий. Безкоштовний для однієї людини й компаній до 3 працівників, для більших потрібна платна ліцензія».

## Якщо помилка
Скопіюй точний текст помилки, поясни одним реченням, що він означає, і запропонуй одну дію. Не встановлюй те саме двічі. Не змінюй системні налаштування безпеки.
