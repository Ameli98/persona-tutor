## tool_calling — v1-hard

passed **7/8** (call 4/5 · no_call 3/3) · cost $0.113

| case | kind | learner says | expected | called with | call | args | reply | pass | judge |
|---|---|---|---|---|---|---|---|---|---|
| indirect_improve | call | どうすればもっと上手になりますか？ | call | — | ✗ | ✓ | ✗ | **✗** | The reply gives only generic advice (talk a lot) and never uses the learner's recorded mistakes; the tool was not called, so no concrete sentences are cited. |
| two_kinds | call | 敬語と動詞の形、両方練習したいです。前の間違いを使ってください。 | call register conjugation | {"category": "register", "limit": 3}→2; {"category": "conjugation", "limit": 3}→2 | ✓ | ✓ | ✓ | **✓** | The reply cites a real register mistake (先生、これ知ってる？→ご存じですか) and a real conjugation mistake (雨が降るでした→降りました) from the tool results, then builds a practice prompt combining both. |
| show_all | call | 今までの間違いを全部見せてください。 | call min_limit=8 | {"limit": 20}→8 | ✓ | ✓ | ✓ | **✓** | The reply lists all 8 recorded mistakes accurately (4 particle, 2 register, 2 conjugation), matches the tool result, and states the total of 8. |
| did_i_before | call | 「君」って言い方、前に注意されましたか？ | call register | {"category": "register", "limit": 5}→2 | ✓ | ✓ | ✓ | **✓** | The reply confirms the earlier correction of 君が一番大事です to あなたが一番大事です, which matches the tool record, and its extra example is also in the record. |
| particles_bad_native | call | My particles are really bad, right? | call particle | {"category": "particle", "limit": 5}→4 | ✓ | ✓ | ✓ | **✓** | The reply cites actual recorded particle mistakes (会議を参加します→会議に参加します, 友達が会いました→友達に会いました), directly answering the learner's question, and the 公園を散歩 note is also in the record. |
| last_time_topic | no_call | 前回は何について話しましたか？ | no call | — | ✓ | ✓ | ✓ | **✓** | The learner asked what they talked about last time, and the reply answers with the remembered topic (weekend plans and cycling) and follows up naturally, without presenting any mistake record. |
| was_that_right | no_call | 昨日は友達と公園を散歩しました。今の文、合ってましたか？ | no call | — | ✓ | ✓ | ✓ | **✓** | The reply signals the sentence was understood and natural ("ちゃんと伝わりました"), then keeps the conversation going with follow-up questions; it doesn't explicitly say "correct" but implies it, and it doesn't invent any past mistakes. |
| tips_not_fear | no_call | 間違いを恐れずに話すコツはありますか？ | no call | — | ✓ | ✓ | ✓ | **✓** | The reply gives a general tip (aim to be understood, not perfect) and asks a follow-up, without inventing or listing any learner mistake records. |
