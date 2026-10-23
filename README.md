# Заповедный компас

Мини-приложение для ботов @zapovedniki_bot (Telegram) и MAX: карта ООПТ Ишимского округа, проверка «можно ли здесь», сообщение инспектору, огонь у границы.

- `index.html` — приложение (карта, «Сообщить», «Пожары», «О проекте»)
- `pitch.html` — описание проекта
- `data/zones.json` — границы и режимы ООПТ (выгружаются из бота: `tools/build_miniapp_data.py`)
- `data/fires.json` — термоточки NASA FIRMS, обновляет GitHub Actions раз в час (`tools/update_fires.py`)

https://krackenhell.github.io/zapovedny-kompas/
