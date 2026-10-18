// UI strings. The language comes from config.yaml `ui_language`. To add one, copy the "en" block.
// {name} placeholders are filled by t(key, {name: ...}).
const STRINGS = {
  en: {
    title: "{tutor} — {target} speaking tutor",
    lang_ja: "Japanese", lang_en: "English", lang_ko: "Korean", lang_zh: "Chinese", lang_yue: "Cantonese",
    connecting: "Connecting…", ready: "Ready", offline: "Backend offline", llm_missing: "LLM not configured",
    llm_missing_detail: "Conversation is unavailable: {msg}",
    transcribing: "Transcribing…", synthesizing: "Synthesizing…", thinking: "{tutor} is thinking…",
    session_over: "Session over", rendering_status: "Making video…",
    now: "Now", cost: "This session ${cost}", cost_title: "From the usage the API reports",
    intro_line: "Press “Start warm-up” to begin.",
    replay: "▶ Replay", show_translation: "Show translation", show_reason: "Show reason", hide: "Hide",
    start_warmup: "Start warm-up", start_warmup_recap: "Start warm-up (recap {n} expressions from last time first)",
    warmup_again: "Warm up again", start_convo: "Start conversation", convo_again: "Another topic",
    topic_random: "Topic: random", rec: "Hold to talk (or hold Space)", recording: "Recording… release to send",
    hint: "Hint", hint_more: "Another hint", retry: "Try again", next: "Next →", finish_warmup: "Finish warm-up",
    end: "End", show_answer: "Show answer",
    my_transcript: "My transcript", feedback: "Feedback", feedback_idle: "Appears here after shadowing or a conversation turn.",
    review: "Review", preparing: "Preparing…", session_log: "This session's transcript",
    history: "Past sessions (review videos)", tts_test: "TTS test", synthesize: "Synthesize",
    topic_warmup: "Warm-up · shadowing", warmup_done: "Warm-up done",
    warmup_done_line: "Nice work. Pick a topic and start a conversation.",
    listen_then_repeat: "Listen, then hold the button and say it.", listen_again: "Listen again, then say it.",
    too_short: "Too short — hold the button for the whole sentence, then release.",
    no_speech_mine: "(no speech recognised)", no_speech: "No speech recognised, please try again.",
    native_question: "own-language question", transcribe_failed: "Transcription failed: {msg}",
    verdict_great: "Great!", verdict_ok: "Mostly right — check the marked parts.", verdict_low: "Listen again and try once more.",
    recall_good: "You remembered it!",
    recall_compare: "Compared with the version saved last time (a different wording with the same meaning is fine too):",
    legend_ok: "green = correct", legend_miss: "red = missing or misread (hover to see what was heard)",
    legend_extra: "yellow = extra", legend_note: "Compared by pronunciation; speech recognition sometimes mishears, so the score is only a guide.",
    said_as: "heard as “{hyp}”", missing: "missing", extra: "extra",
    mic_failed: "Cannot use the microphone: {msg}", checking: "Checking…",
    not_graded: "(own-language question — not graded)", feedback_unavailable: "Feedback unavailable ({msg})",
    natural: "✓ Natural", fb_said: "What I said", fb_better: "More natural", fb_why: "Why",
    convo_intro: "When something sounds off, a more natural phrasing appears here (natural answers are left alone).",
    error: "Error: {msg}",
    review_loading: "Preparing corrected versions, model answers and key expressions… (10–20 s)",
    review_key: "Key expressions (recapped at the start of next time)", review_lines: "Line by line",
    review_video: "Review video", i_said: "I said", corrected: "Corrected", model: "Model", fine_as_is: "✓ Fine as it was",
    own_language: "own language", saved_to: "Saved to data/sessions/{dir}/", review_failed: "Review failed: {msg}",
    topic_recap: "Recap · key expressions from last time",
    recap_note: "This is what you said last time. Hold the button and say it more naturally.",
    recap_hint: "Can't remember? Press “Show answer”.",
    looking_up: "Looking up…", lookup_failed: "Lookup failed: {msg}", example: "e.g. {text}",
    keywords: "Keywords", model_answer: "Model answer",
    mode_corrected: "Corrected version", mode_upgraded: "Model version", shadowing: " · shadowing",
    explain_modes: "Corrected = your own words with only the unnatural parts fixed. Model = how a native speaker might answer here: same meaning, fuller (reasons, examples, responding to the other person).",
    explain_corrected_video: "your lines replaced by the corrected versions — see what to fix",
    explain_upgraded_video: "your lines replaced by the model answers — learn fuller, more natural ways to say it",
    download_mp3: "Download mp3", make_video: "Make review video", remake_video: "Make it again",
    video_note: "Your lines are re-spoken by the review voice. About 1 min for a short session, 2–3 min for 12 minutes; practice is paused meanwhile.",
    no_history: "No reviewed sessions yet.",
    p_voice_loading: "Loading the review voice…", p_voicing: "Voicing {n} lines (same-emotion lines together, each checked by speech recognition)…",
    p_voice_retry: "  [{emotion}] {status} after {retries} retries: {text}", p_ok: "✓", p_failed: "⚠ failed the check",
    p_voice_restored: "Switched back to {tutor}'s voice", p_rendering: "Rendering videos…", p_video_done: "Done: {file} ({seconds} s)",
    e_no_review: "This session has no review yet.", e_already_rendering: "A video is already being made.",
    e_no_speech: "No speech recognised, please try again.",
    tts_unverified: "⚠ not verified", tts_rephrased: " · rephrased", tts_attempts: " · synthesized {n} times",
  },
  "zh-TW": {
    title: "{tutor}・{target}口說家教",
    lang_ja: "日文", lang_en: "英文", lang_ko: "韓文", lang_zh: "中文", lang_yue: "粵語",
    connecting: "連線中…", ready: "就緒", offline: "後端未連線", llm_missing: "LLM 未設定",
    llm_missing_detail: "對話功能無法使用：{msg}",
    transcribing: "轉寫中…", synthesizing: "合成中…", thinking: "{tutor}思考中…",
    session_over: "練習結束", rendering_status: "產生影片中…",
    now: "目前", cost: "本次 ${cost}", cost_title: "依 API 回報的實際用量計算",
    intro_line: "按「開始暖身」開始。",
    replay: "▶ 再聽一次", show_translation: "顯示翻譯", show_reason: "看原因", hide: "隱藏",
    start_warmup: "開始暖身", start_warmup_recap: "開始暖身（先複習上次的 {n} 個表達）",
    warmup_again: "再做一次暖身", start_convo: "開始對話", convo_again: "再聊一個話題",
    topic_random: "話題：隨機", rec: "按住說話（或按住空白鍵）", recording: "錄音中…放開送出",
    hint: "提示", hint_more: "再一個提示", retry: "再試一次", next: "下一句 →", finish_warmup: "完成暖身",
    end: "結束", show_answer: "看答案",
    my_transcript: "我的轉寫", feedback: "回饋", feedback_idle: "跟讀或對話後會在這裡顯示。",
    review: "復盤", preparing: "整理中…", session_log: "本次對話紀錄",
    history: "過去的練習（復盤影片）", tts_test: "TTS 測試", synthesize: "合成",
    topic_warmup: "暖身・跟讀", warmup_done: "暖身完成",
    warmup_done_line: "辛苦了。選一個話題開始聊吧。",
    listen_then_repeat: "聽完後按住按鈕跟著說一次。", listen_again: "再聽一次，然後跟著說。",
    too_short: "錄音太短，請按住按鈕說完整句再放開。",
    no_speech_mine: "（沒有辨識到語音）", no_speech: "沒有辨識到語音，請再說一次。",
    native_question: "母語提問", transcribe_failed: "轉寫失敗：{msg}",
    verdict_great: "很好！", verdict_ok: "大致正確，注意標示的地方。", verdict_low: "再聽一次試試看。",
    recall_good: "想起來了！",
    recall_compare: "和上次整理的說法比較（意思對、說法不同也可以）：",
    legend_ok: "綠＝正確", legend_miss: "紅＝漏掉或唸錯（滑鼠移上去看唸成什麼）",
    legend_extra: "黃＝多出來的", legend_note: "比對的是讀音；語音辨識偶爾會聽錯，分數僅供參考。",
    said_as: "唸成「{hyp}」", missing: "漏掉", extra: "多出",
    mic_failed: "無法使用麥克風：{msg}", checking: "檢查中…",
    not_graded: "（母語提問，不糾錯）", feedback_unavailable: "回饋暫時無法取得（{msg}）",
    natural: "✓ 很自然", fb_said: "我說的", fb_better: "更自然的說法", fb_why: "原因",
    convo_intro: "回答後會在這裡顯示更自然的說法（說得自然就不會挑錯）。",
    error: "錯誤：{msg}",
    review_loading: "整理本次的修正版、範本與重點表達中…（約 10–20 秒）",
    review_key: "本次重點表達（下次開頭會複習）", review_lines: "逐句復盤",
    review_video: "復盤影片", i_said: "我說的", corrected: "修正", model: "範本", fine_as_is: "✓ 原句即可",
    own_language: "母語", saved_to: "已存到 data/sessions/{dir}/", review_failed: "復盤整理失敗：{msg}",
    topic_recap: "複習・上次的重點表達",
    recap_note: "上次你這樣說。按住按鈕，用更自然的說法再說一次。",
    recap_hint: "想不起來就按「看答案」。",
    looking_up: "查詢中…", lookup_failed: "查詢失敗：{msg}", example: "例：{text}",
    keywords: "關鍵詞", model_answer: "示範",
    mode_corrected: "修正版", mode_upgraded: "範本版", shadowing: "・跟讀",
    explain_modes: "修正＝保留你的用字，只改不自然的地方。範本＝母語者在這個情境會怎麼回答：意思不變，但更完整（理由、例子、回應對方）。",
    explain_corrected_video: "你的台詞換成修正版：看自己哪裡要改",
    explain_upgraded_video: "你的台詞換成範本：學更完整、更自然的說法",
    download_mp3: "下載 mp3", make_video: "產生復盤影片", remake_video: "重新產生影片",
    video_note: "你的台詞由復盤聲音重唸；短的練習約 1 分鐘、12 分鐘的練習約 2–3 分鐘，期間不能練習。",
    no_history: "還沒有做過復盤的練習。",
    p_voice_loading: "載入復盤用的聲音…", p_voicing: "配音 {n} 句（同語氣的句子一起合成，再逐句用語音辨識檢查）…",
    p_voice_retry: "  [{emotion}] {status}，重做 {retries} 次：{text}", p_ok: "✓", p_failed: "⚠ 未通過檢查",
    p_voice_restored: "已切回{tutor}的聲音", p_rendering: "輸出影片中…", p_video_done: "完成 {file}（{seconds} 秒）",
    e_no_review: "這次練習還沒有復盤稿。", e_already_rendering: "已經在產生影片了。",
    e_no_speech: "沒有辨識到語音，請再說一次。",
    tts_unverified: "⚠ 未通過比對", tts_rephrased: " · 已換說法", tts_attempts: " · 合成 {n} 次",
  },
};

let LANG = "en";
const VARS = {};   // always-available placeholders (tutor name, target language)

function setLanguage(code, vars = {}) {
  LANG = STRINGS[code] ? code : "en";
  Object.assign(VARS, vars);
  document.documentElement.lang = LANG;
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
  document.title = t("title");
}

function t(key, vars = {}) {
  const s = STRINGS[LANG][key] ?? STRINGS.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : k in VARS ? VARS[k] : m));
}

// backend messages arrive as keys: {"key": "no_speech"} or HTTP detail "already_rendering"
function tMsg(keyOrText, prefix = "e_") {
  return STRINGS.en[prefix + keyOrText] ? t(prefix + keyOrText) : keyOrText;
}
