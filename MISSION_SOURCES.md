# Источники миссий

Я не копирую сюда полные тексты чужих карточек: официальные карточки и многие фанатские PDF/колоды защищены авторскими правами. Но бот уже готов принять полную базу, если ты вручную добавишь тексты в JSON-файлы из своих материалов или из источников, где тебе можно ими пользоваться.

Полезные найденные источники:

- Scribd: `18 Objectives Fanmade Nemesis LD (EN) v1.1` — фанатские цели для Nemesis: Lockdown.
  https://www.scribd.com/document/814883387/18-Objectives-Fanmade-Nemesis-LD-EN-v1-1
- Ludopedia: `Arquivos PnP extras!` — описание PnP-набора, где указаны 9 корпоративных и 9 личных целей.
  https://ludopedia.com.br/jogo/nemesis/anexos/208414
- Etsy: `36 Fan Made Nemesis Board Game Objective Cards Expansion` — платная фанатская цифровая колода на 18 personal и 18 corporate целей.
  https://www.etsy.com/au/listing/4407443227/36-fan-made-nemesis-board-game-objective
- Gamerules: обзор правил Nemesis, где описана раздача одной корпоративной и одной личной цели каждому игроку.
  https://gamerules.com/rules/nemesis/

Дополнительно найдено:

- Tesera / Yandex Disk: `Расширенный набор целей (корпорации и личных)` — самый похожий источник на PnP-карточки для печати. В описании указано, что PDF содержит базовые цели и дополнительные цели: +9 корпоративных и +9 личных, дополнительные помечены значком в правом углу. Также указано, что набор сделан на основе миссий с BGG с правками баланса.
  https://disk.yandex.ru/i/Is5SLl-eINu39Q
  Страница-указатель на Tesera:
  https://tesera.ru/game/nemesis/files/link/
  Из этого PDF в JSON добавлены только переформулированные варианты целей, без дословного копирования текста карточек.
- Tesera / valdar: `Немезида: Альтернативные карты целей` — старый фанатский набор с текстовыми альтернативными целями. В описании упоминаются поиск и спасение Джонси, а также скрытый Андроид.
  https://tesera.ru/game/nemesis/diaries/
  Прямая ссылка из записи:
  https://yadi.sk/i/8VdRpAKV49Lrzg
  DOCX-зеркало на Tesera:
  https://tesera.ru/images/items/1762391/Tseli_Nemezida_Valdar.docx
- Ludopedia / Compara Jogos: `Arquivos PnP extras!` / `NEMESIS - Arquivo editável PnP adicionais` — португальский PnP-пак, где указаны 9 Objetivos Corporativos и 9 Objetivos Pessoais; в обсуждении упоминаются карточки `Código Morse`, `Proteja o Vip`, `A Cura`.
  https://ludopedia.com.br/jogo/nemesis/anexos/208414
  https://www.comparajogos.com.br/f/t/nemesis-arquivo-editavel-pnp-adicionais/46951
- Steam Workshop: `Nemesis Custom Objectives & Serious Wounds Pack` — англоязычный набор для Tabletop Simulator с дополнительными Personal & Corporate Objectives и Serious Wounds. Важно: страница сейчас помечена Steam как удаленная/несовместимая, поэтому источник может быть недоступен без подписки или старых файлов Workshop.
  https://steamcommunity.com/sharedfiles/filedetails/?id=2835750373

Формат переноса в бота:

```json
{
  "id": "corp_001",
  "title": "Название карточки",
  "text": "Текст цели",
  "source": "base / fan / pnp / твоя пометка"
}
```
