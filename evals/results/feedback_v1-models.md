## feedback — v1-models

| model | passed | fine | stiff | error | misheard | fine lines called mistakes | median time | cost |
|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | 32/36 | 8/8 | 6/7 | 11/13 | 7/8 | 1/15 | 1.8 s | $0.037 |
| claude-haiku-5-5 | 29/36 | 7/8 | 5/7 | 11/13 | 6/8 | 3/15 | 1.9 s | $0.005 |
| claude-opus-5-5 | 33/36 | 8/8 | 5/7 | 12/13 | 8/8 | 2/15 | 2.0 s | $0.095 |

Failures:
- claude-sonnet-5-5 `hard_err_i_adj`: 大きいな家に住んでいます → error 大きい家に住んでいます
- claude-sonnet-5-5 `hard_err_literal`: 映画を看ると思う行きます → misheard 映画を見に行きます
- claude-sonnet-5-5 `hard_stiff_literary`: 多忙な日々を過ごしております → error 最近は忙しい毎日を過ごしています
- claude-sonnet-5-5 `hard_mis_kanji`: 東京の夏は熱いです。汗をかきます → error 東京の夏は暑いです。汗をかきます
- claude-haiku-5-5 `fine_question_mark`: そうですね？本当に寒いです？ → error そうですね。本当に寒いですね。
- claude-haiku-5-5 `stiff_often`: 休日は映画を鑑賞することが多いです → error 休みの日は映画を見ることが多いです
- claude-haiku-5-5 `err_ride`: バスを乗りました → error バスで来ました
- claude-haiku-5-5 `hard_err_i_adj`: 大きいな家に住んでいます → error 大きい家に住んでいます
- claude-haiku-5-5 `hard_stiff_literary`: 多忙な日々を過ごしております → error 最近忙しい日々を過ごしています
- claude-haiku-5-5 `hard_mis_kanji`: 東京の夏は熱いです。汗をかきます → error 東京の夏は暑いです。汗をかきます。
- claude-haiku-5-5 `hard_mis_name`: 土曜日は陶器に行きます。一泊します → misheard 土曜日は陶芸に行きます。一泊します
- claude-opus-5-5 `stiff_however`: 楽しかったです。しかし少し疲れました → error 楽しかったです。でも少し疲れました
- claude-opus-5-5 `hard_err_i_adj`: 大きいな家に住んでいます → error 大きい家に住んでいます
- claude-opus-5-5 `hard_stiff_literary`: 多忙な日々を過ごしております → error 最近ずっと忙しいです
