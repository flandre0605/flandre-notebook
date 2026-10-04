# 芙兰桌宠表情差分

使用内置图像生成工具，参考 `assets/flandre_pet_chibi.png`，每种表情独立编辑生成。透明背景，保留全身造型。

| 文件 | 表情 | 自动触发 |
| --- | --- | --- |
| flandre_pet_chibi.png | 待机 | 尚未输入答案 |
| pet_expressions/happy.png | 开心 | 鼠标悬停、答对、完成本轮 |
| pet_expressions/thinking.png | 思考 | 输入答案或跳过 |
| pet_expressions/sad.png | 委屈 | 答错 |
| pet_expressions/sleepy.png | 困倦 | 收起且无互动 45 秒 |
| pet_expressions/surprised.png | 惊讶 | 拖动角色或答题卡标题 |

表情只影响显示，不写入题库，不更改评分。拖动、悬停和困倦优先于练习表情，结束互动后恢复当前练习对应的表情。展开或鼠标移入角色会唤醒；返回完整界面时停止计时器并断开练习信号。

## 最终提示词

### 开心 (`happy.png`)

Use case: identity-preserve. Edit the supplied transparent full-body chibi Flandre desktop pet sprite into one facial-expression variant. Keep the exact same character, illustration style, canvas size, framing, full-body pose, all body and hand positions, book, cap, red ribbon, golden hair, red-and-white outfit, shoes, crystal wings, silhouette, scale and feet baseline. Change ONLY eyes, eyebrows, mouth and tiny blush marks inside the existing face area. The full body must stay perfectly aligned to the reference for expression switching in a desktop pet application. No additional symbols, objects, text, bubbles, backgrounds, outlines around the asset, or shadows. Preserve actual transparent RGBA background. Output a single full-body sprite, not a collage, contact sheet or sprite sheet. Expression to create: Very happy and pleased: joyful closed upward-curving eyes, soft raised eyebrows, a broad delighted smiling mouth and rosy cheeks. Cute celebratory expression.

### 思考 (`thinking.png`)

Use case: identity-preserve. Edit the supplied transparent full-body chibi Flandre desktop pet sprite into one facial-expression variant. Keep the exact same character, illustration style, canvas size, framing, full-body pose, all body and hand positions, book, cap, red ribbon, golden hair, red-and-white outfit, shoes, crystal wings, silhouette, scale and feet baseline. Change ONLY eyes, eyebrows, mouth and tiny blush marks inside the existing face area. The full body must stay perfectly aligned to the reference for expression switching in a desktop pet application. No additional symbols, objects, text, bubbles, backgrounds, outlines around the asset, or shadows. Preserve actual transparent RGBA background. Output a single full-body sprite, not a collage, contact sheet or sprite sheet. Expression to create: Concentrating thoughtfully: open ruby-red eyes glancing slightly upward to one side, one slightly raised eyebrow, and a small thoughtful pursed mouth. Gentle curious expression, not angry.

### 委屈 (`sad.png`)

Use case: identity-preserve. Edit the supplied transparent full-body chibi Flandre desktop pet sprite into one facial-expression variant. Keep the exact same character, illustration style, canvas size, framing, full-body pose, all body and hand positions, book, cap, red ribbon, golden hair, red-and-white outfit, shoes, crystal wings, silhouette, scale and feet baseline. Change ONLY eyes, eyebrows, mouth and tiny blush marks inside the existing face area. The full body must stay perfectly aligned to the reference for expression switching in a desktop pet application. No additional symbols, objects, text, bubbles, backgrounds, outlines around the asset, or shadows. Preserve actual transparent RGBA background. Output a single full-body sprite, not a collage, contact sheet or sprite sheet. Expression to create: Mildly disappointed but cute: slightly watery ruby-red eyes, lowered raised-in-the-middle eyebrows and a tiny downward-curving mouth. No tears falling outside the face; no dramatic crying.

### 困倦 (`sleepy.png`)

Use case: identity-preserve. Edit the supplied transparent full-body chibi Flandre desktop pet sprite into one facial-expression variant. Keep the exact same character, illustration style, canvas size, framing, full-body pose, all body and hand positions, book, cap, red ribbon, golden hair, red-and-white outfit, shoes, crystal wings, silhouette, scale and feet baseline. Change ONLY eyes, eyebrows, mouth and tiny blush marks inside the existing face area. The full body must stay perfectly aligned to the reference for expression switching in a desktop pet application. No additional symbols, objects, text, bubbles, backgrounds, outlines around the asset, or shadows. Preserve actual transparent RGBA background. Output a single full-body sprite, not a collage, contact sheet or sprite sheet. Expression to create: Dozing peacefully: both eyes softly closed with relaxed eyebrows and a tiny quiet sleeping mouth. Peaceful drowsy face, no Z letters or sleep bubble.

### 惊讶 (`surprised.png`)

Use case: identity-preserve. Edit the supplied transparent full-body chibi Flandre desktop pet sprite into one facial-expression variant. Keep the exact same character, illustration style, canvas size, framing, full-body pose, all body and hand positions, book, cap, red ribbon, golden hair, red-and-white outfit, shoes, crystal wings, silhouette, scale and feet baseline. Change ONLY eyes, eyebrows, mouth and tiny blush marks inside the existing face area. The full body must stay perfectly aligned to the reference for expression switching in a desktop pet application. No additional symbols, objects, text, bubbles, backgrounds, outlines around the asset, or shadows. Preserve actual transparent RGBA background. Output a single full-body sprite, not a collage, contact sheet or sprite sheet. Expression to create: Surprised when picked up: widened ruby-red eyes, gently lifted eyebrows, and a small round open O mouth. Friendly startled expression, not fear.
