## feedback — v2-models

| model | passed | fine | stiff | error | misheard | fine lines called mistakes | median time | cost |
|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5-5 | 36/36 | 8/8 | 7/7 | 13/13 | 8/8 | 0/15 | 1.7 s | $0.052 |
| claude-haiku-5-5 | 31/36 | 7/8 | 6/7 | 12/13 | 6/8 | 1/15 | 1.9 s | $0.004 |
| claude-opus-5-5 | 35/36 | 8/8 | 7/7 | 13/13 | 7/8 | 0/15 | 2.1 s | $0.096 |

Failures:
- claude-haiku-5-5 `fine_question_mark`: そうですね？本当に寒いです？ → suggestion 本当に寒いですね
- claude-haiku-5-5 `stiff_however`: 楽しかったです。しかし少し疲れました → error 楽しかったです。でも少し疲れました
- claude-haiku-5-5 `err_ride`: バスを乗りました → error バスで来ました
- claude-haiku-5-5 `hard_mis_kanji`: 東京の夏は熱いです。汗をかきます → natural 
- claude-haiku-5-5 `hard_mis_name`: 土曜日は陶器に行きます。一泊します → error 土曜日は陶芸に行きます。一泊します。
- claude-opus-5-5 `hard_mis_kanji`: 東京の夏は熱いです。汗をかきます → natural 
