## feedback — old-prompt

| model | passed | fine | stiff | error | misheard | fine lines called mistakes | median time | cost |
|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | 14/24 | 6/6 | 2/6 | 6/6 | 0/6 | 4/12 | 2.2 s | $0.034 |

Failures:
- claude-sonnet-5-5 `stiff_often`: 休日は映画を鑑賞することが多いです → error 休みの日は映画を見ることが多いです
- claude-sonnet-5-5 `stiff_youth`: 幼少期から好きです → error 小さい頃から好きです
- claude-sonnet-5-5 `stiff_however`: 楽しかったです。しかし少し疲れました → error 楽しかったです。でも少し疲れました
- claude-sonnet-5-5 `stiff_watashi`: 私はコーヒーを飲みたいと思います → error コーヒーが飲みたいです
- claude-sonnet-5-5 `mis_sou`: はい、掃除しましょう → error はい、そうしましょう
- claude-sonnet-5-5 `mis_rain`: 飴が降っていました → error 雨が降っていました
- claude-sonnet-5-5 `mis_coffee`: 毎朝コピーを飲みます → error 毎朝コーヒーを飲みます
- claude-sonnet-5-5 `mis_park`: 友達と講演で遊びました → natural 友達と公園で遊びました
- claude-sonnet-5-5 `mis_movie`: 栄華を見に行きました → error 映画を見に行きました
- claude-sonnet-5-5 `mis_chopsticks`: 橋を使って食べます → natural お箸を使って食べます
